#!/usr/bin/env python3
"""
HTTP/3 (QUIC) test server using aioquic >=1.0.

Endpoints:
  /                     -> hello
  /echo                 -> echo POST/PUT body
  /100pps_10s           -> send 1250B packets at 100pps for 10s
  /50pps_1min           -> send 1250B packets at 50pps for 60s
"""

import argparse
import asyncio
import os
import re
import time
from typing import Dict

from aioquic.asyncio import QuicConnectionProtocol, serve
from aioquic.h3.connection import H3_ALPN, H3Connection
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent


class H3Server(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._http: H3Connection | None = None
        self._buffers: Dict[int, bytearray] = {}

    def quic_event_received(self, event: QuicEvent) -> None:
        if self._http is None:
            self._http = H3Connection(self._quic)

        # aioquic ≥1.0 API: handle_event() yields HTTP events directly
        for http_event in self._http.handle_event(event):
            if isinstance(http_event, HeadersReceived):
                self._on_headers(http_event)
            elif isinstance(http_event, DataReceived):
                self._on_data(http_event)

    def _on_headers(self, ev: HeadersReceived):
        sid = ev.stream_id
        hdrs = dict(ev.headers)
        method = hdrs.get(b":method", b"GET").decode()
        path = hdrs.get(b":path", b"/").decode()

        m = re.match(r"/(\d+)pps_(\d+)(s|min)", path)
        if method == "GET" and m:
            rate = int(m.group(1))
            dur = int(m.group(2)) * (60 if m.group(3) == "min" else 1)
            asyncio.ensure_future(self._rate_send(sid, rate, dur))
            return

        if method == "GET" and path == "/":
            self._send_resp(sid, 200, b"Hello from HTTP/3 QUIC test server\n")
            return

        if method in ("POST", "PUT") and path.startswith("/echo"):
            self._buffers.setdefault(sid, bytearray())
            return

        self._send_resp(sid, 404, b"Not found\n")

    def _on_data(self, ev: DataReceived):
        sid = ev.stream_id
        buf = self._buffers.setdefault(sid, bytearray())
        buf.extend(ev.data)
        if ev.stream_ended:
            body = bytes(buf)
            self._buffers.pop(sid, None)
            self._send_resp(sid, 200, body)

    def _send_resp(self, sid: int, code: int, body: bytes):
        assert self._http
        hdrs = [
            (b":status", str(code).encode()),
            (b"server", b"aioquic-h3"),
            (b"content-type", b"text/plain"),
            (b"content-length", str(len(body)).encode()),
        ]
        self._http.send_headers(sid, hdrs)
        self._http.send_data(sid, body, end_stream=True)
        self.transmit()

    async def _rate_send(self, sid: int, rate: int, dur: int):
        """Send 1250-byte QUIC stream chunks at a fixed rate for the given duration."""
        assert self._http
        hdrs = [
            (b":status", b"200"),
            (b"server", b"aioquic-h3"),
            (b"content-type", b"application/octet-stream"),
        ]
        self._http.send_headers(sid, hdrs, end_stream=False)
        self.transmit()

        # QUIC payload target per datagram (RFC 9000 safe limit)
        quic_payload_size = 1250
        interval = 1.0 / rate
        total = rate * dur
        filler = b"X" * quic_payload_size

        t0 = time.time()
        for i in range(total):
            hdr = f"pkt-{i:05d}\n".encode()
            pad_len = quic_payload_size - len(hdr)
            if pad_len < 0:
                pad_len = 0
            chunk = hdr + filler[:pad_len]

            self._http.send_data(sid, chunk, end_stream=False)
            self.transmit()

            await asyncio.sleep(interval)
            if time.time() - t0 >= dur:
                break

        # End the stream
        self._http.send_data(sid, b"", end_stream=True)
        self.transmit()
        print(f"[rate_send] Sent {total} packets @ {rate}pps for {dur}s (1250B each)")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--private-key", required=True)
    args = parser.parse_args()

    config = QuicConfiguration(is_client=False, alpn_protocols=H3_ALPN)
    config.load_cert_chain(args.certificate, args.private_key)
    os.makedirs("/keys", exist_ok=True)
    config.secrets_log_file = open("/keys/quic_keylog.log", "a")

    print(f"Serving HTTP/3 on {args.host}:{args.port}")
    server = await serve(args.host, args.port, configuration=config, create_protocol=H3Server)
    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())

