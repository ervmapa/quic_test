QUIC HTTP/3 Test Environment

This setup provides a self-contained QUIC
(HTTP/3) testbed. Includes a Python QUIC server,
a client with HTTP/3 support.

Features:

QUIC + HTTP/3 server implemented with aioquic
Automatically generated self-signed TLS certificates
Packet capture using tcpdump
Traffic rate control via URI (example: /100pps_1min)

Components:

h3_server.py: Python QUIC HTTP/3 server
Dockerfile.server: builds the QUIC server container
captures/: directory for pcap captures (host-mounted)
certs/: directory for TLS certs (auto-generated)

Build and start:
sudo docker-compose up -d --build

Check logs:
docker logs quic-server

Expected output:
Serving HTTP/3 on 0.0.0.0:4433

Server behavior:
The server listens on UDP port 4433 and supports rate-controlled URIs.

Examples:
/100pps_1min -> sends 100 packets per second for 1 minute
/10pps_5s -> sends 10 packets per second for 5 seconds
Packets are 1300 bytes each.
curl -k --http3 https://server3.test.local/100pps_10s 

Capturing QUIC traffic:

Inside container:
docker exec -it quic-server tcpdump -i eth0 -w /captures/quic_capture.pcap udp port 443

On the host with real Ethernet headers:
NETID=$(docker network ls | awk '/quic_test/ {print $1}')
sudo tcpdump -i br-$NETID -w quic_real_eth.pcap udp port 443

tcpdump -i br-$(docker network ls | grep quic_test | awk '{print $1}')


Output files appear in:
/captures/converted/*.pcap

Each file includes:
Ethernet II header
Source MAC: 02:aa:bb:00:00:01
Destination MAC: 02:aa:bb:00:00:02

Typical directory layout:

quic_test/
├── h3_server.py
├── Dockerfile.server
├── docker-compose.yaml
├── captures/
│ ├── quic_capture1.pcap
│ └── quic_capture1_mac.pcap
└── certs/
├── cert.pem
└── key.pem
