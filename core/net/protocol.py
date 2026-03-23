"""Shared JSON message tags for the TCP relay (v1).

Envelope (see server/tcp_relay.py): join, client_msg, relay, joined, peer_left.

Application payloads live in relay `body` / client_msg `body`. See app_messages.py.
"""

RELAY_PROTOCOL_V1 = 1
