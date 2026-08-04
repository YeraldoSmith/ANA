"""
ANA Chain Protocol — AI-Native Communication Protocol

A codon-based communication protocol for AI Agent <-> API communication
that eliminates JSON serialization overhead through pre-shared codebooks.

Author:  Yeraldo Smith (https://github.com/YeraldoSmith)
License: AGPL-3.0-or-later
"""

__version__ = "0.3.0"
__author__ = "Yeraldo Smith"
__github__ = "https://github.com/YeraldoSmith/ANA"
__protocol_version__ = 1

from ana.codebook import (
    Codebook, CodebookVersion, ServiceDef, OperationDef, TemplateDef,
    derive_hmac_key,
)
from ana.codon import (
    CodonEncoder, CodonDecoder,
    encode_varint, decode_varint,
    encode_params, decode_params,
)
from ana.packet import (
    Packet, PacketType, PacketFlags, serialize_packet, deserialize_packet,
    make_negotiate, make_negotiate_ack, make_negotiate_confirm,
    make_codon, make_codon_ack, make_rotate, make_rotate_ack,
    make_error, make_fallback,
    compute_hmac, verify_hmac,
    ErrorCode, MAGIC, HEADER_SIZE, PACKET_OVERHEAD,
    CAP_HMAC, HMAC_TAG_SIZE,
)
from ana.session import Session, SessionState, SessionConfig
from ana.transport import UDPSender, UDPReceiver, NoiseGenerator
from ana.negotiator import Negotiator, NegotiationResult
from ana.fallback import FallbackHandler, JSONFallbackCodec
from ana.security import (
    ANAIdentity, ANASecureSession, AEADCipher,
    HelloPacket, HelloAckPacket,
)
from ana.reliability import (
    ReliableSession, ACKTracker, Heartbeat, BloomFilter,
    CodonEvent, AckEvent, PingEvent, PongEvent,
    ErrorEvent, TimeoutEvent, PeerDeadEvent, ChainMismatchEvent,
    make_ping_codon, make_pong_codon, make_teardown_codon,
    parse_codon_payload,
)

__all__ = [
    # Codebook
    "Codebook", "CodebookVersion", "ServiceDef", "OperationDef", "TemplateDef",
    "derive_hmac_key",
    # Codon
    "CodonEncoder", "CodonDecoder",
    "encode_varint", "decode_varint", "encode_params", "decode_params",
    # Packet
    "Packet", "PacketType", "PacketFlags", "serialize_packet", "deserialize_packet",
    "make_negotiate", "make_negotiate_ack", "make_negotiate_confirm",
    "make_codon", "make_codon_ack", "make_rotate", "make_rotate_ack",
    "make_error", "make_fallback",
    "compute_hmac", "verify_hmac",
    "parse_codon_payload",
    "ErrorCode", "MAGIC", "HEADER_SIZE", "PACKET_OVERHEAD",
    "CAP_HMAC", "HMAC_TAG_SIZE",
    # Session
    "Session", "SessionState", "SessionConfig",
    # Transport
    "UDPSender", "UDPReceiver", "NoiseGenerator",
    # Negotiation
    "Negotiator", "NegotiationResult",
    # Fallback
    "FallbackHandler", "JSONFallbackCodec",
    # Security (ANA-S)
    "ANAIdentity", "ANASecureSession", "AEADCipher",
    "HelloPacket", "HelloAckPacket",
    # Reliability
    "ReliableSession", "ACKTracker", "Heartbeat", "BloomFilter",
    "CodonEvent", "AckEvent", "PingEvent", "PongEvent",
    "ErrorEvent", "TimeoutEvent", "PeerDeadEvent", "ChainMismatchEvent",
    "make_ping_codon", "make_pong_codon", "make_teardown_codon",
]
