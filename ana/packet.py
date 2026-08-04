"""
ANA Chain packet serialization.

Packet format (without HMAC):
  [magic: u16][version: u8][flags: u8][stream_id: u16][seq: u32]
  [payload_len: u16][payload: bytes][checksum: u16]

Packet format (with HMAC, negotiated capability):
  [magic: u16][version: u8][flags: u8][stream_id: u16][seq: u32]
  [payload_len: u16][payload: bytes][crc16: u16][hmac: u16*8]

All multi-byte fields are big-endian.
"""

import struct
import enum
import hmac as _hmac
import hashlib
from typing import Optional


MAGIC = 0xA7A7
PROTOCOL_VERSION = 0x01
HEADER_SIZE = 12
CHECKSUM_SIZE = 2
HMAC_TAG_SIZE = 16      # HMAC-SHA256 truncated to 128 bits
HMAC_OVERHEAD = HMAC_TAG_SIZE
PACKET_OVERHEAD = HEADER_SIZE + CHECKSUM_SIZE  # 14 bytes (without HMAC)
PACKET_OVERHEAD_HMAC = HEADER_SIZE + CHECKSUM_SIZE + HMAC_TAG_SIZE  # 30 bytes

# Capability flags
CAP_CODON = 1 << 0
CAP_NOISE = 1 << 1
CAP_FRAGMENT = 1 << 2
CAP_ROTATE = 1 << 3
CAP_HMAC = 1 << 4       # HMAC-SHA256 integrity protection

ALLOWED_SIZES = [64, 128, 256, 512, 1024]


class PacketType(enum.IntEnum):
    NEGOTIATE = 0x00
    NEGOTIATE_ACK = 0x01
    NEGOTIATE_CONFIRM = 0x02
    CODON = 0x03
    ROTATE = 0x04
    ROTATE_ACK = 0x05
    ERROR = 0x06
    FALLBACK = 0x07


class PacketFlags:
    """Bit flags encoded in the flags byte."""
    # Low 3 bits: packet type
    TYPE_MASK = 0x07
    # Bit 3: has noise codons in payload
    HAS_NOISE = 0x08
    # Bit 4: payload is fragmented (more packets follow)
    IS_FRAGMENTED = 0x10
    # Bit 5: ACK — this CODON packet is an acknowledgment
    IS_ACK = 0x20
    # Bits 6-7: reserved

    @staticmethod
    def pack(packet_type: PacketType, has_noise: bool = False,
             is_fragmented: bool = False, is_ack: bool = False) -> int:
        return (int(packet_type) & PacketFlags.TYPE_MASK) \
               | (PacketFlags.HAS_NOISE if has_noise else 0) \
               | (PacketFlags.IS_FRAGMENTED if is_fragmented else 0) \
               | (PacketFlags.IS_ACK if is_ack else 0)

    @staticmethod
    def unpack(flags: int) -> tuple[PacketType, bool, bool, bool]:
        ptype = PacketType(flags & PacketFlags.TYPE_MASK)
        has_noise = bool(flags & PacketFlags.HAS_NOISE)
        fragmented = bool(flags & PacketFlags.IS_FRAGMENTED)
        is_ack = bool(flags & PacketFlags.IS_ACK)
        return ptype, has_noise, fragmented, is_ack


# CRC-16/CCITT table (precomputed)
_CRC16_TABLE = None


def _make_crc16_table():
    global _CRC16_TABLE
    if _CRC16_TABLE is not None:
        return _CRC16_TABLE
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        table.append(crc)
    _CRC16_TABLE = table
    return table


def crc16(data: bytes) -> int:
    """Compute CRC-16/CCITT of data (error detection, NOT tamper resistance)."""
    table = _make_crc16_table()
    crc = 0xFFFF
    for byte in data:
        crc = ((crc << 8) ^ table[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
    return crc


def compute_hmac(key: bytes, data: bytes) -> bytes:
    """Compute HMAC-SHA256 tag, truncated to 16 bytes (128 bits).

    This provides cryptographic integrity protection.
    CRC-16 catches accidental errors; HMAC catches active attacks.
    """
    return _hmac.new(key, data, hashlib.sha256).digest()[:HMAC_TAG_SIZE]


def verify_hmac(key: bytes, data: bytes, tag: bytes) -> bool:
    """Verify an HMAC-SHA256 tag using constant-time comparison."""
    expected = compute_hmac(key, data)
    return _hmac.compare_digest(expected, tag)


# ---------------------------------------------------------------------------
# Packet class
# ---------------------------------------------------------------------------


class Packet:
    """Represents an ANA chain packet."""

    __slots__ = ('packet_type', 'flags', 'stream_id', 'sequence', 'payload')

    def __init__(self, packet_type: PacketType, stream_id: int = 0,
                 sequence: int = 0, payload: bytes = b'',
                 has_noise: bool = False, is_fragmented: bool = False,
                 is_ack: bool = False):
        self.packet_type = packet_type
        self.flags = PacketFlags.pack(packet_type, has_noise, is_fragmented, is_ack)
        self.stream_id = stream_id
        self.sequence = sequence
        self.payload = payload

    @property
    def has_noise(self) -> bool:
        return bool(self.flags & PacketFlags.HAS_NOISE)

    @property
    def is_fragmented(self) -> bool:
        return bool(self.flags & PacketFlags.IS_FRAGMENTED)

    @property
    def is_ack(self) -> bool:
        return bool(self.flags & PacketFlags.IS_ACK)

    def __repr__(self) -> str:
        extra = []
        if self.is_ack: extra.append("ACK")
        if self.is_fragmented: extra.append("FRAG")
        tag = "+".join(extra) if extra else ""
        return (f"Packet(type={self.packet_type.name}{'+' + tag if tag else ''}, "
                f"stream={self.stream_id}, seq={self.sequence}, "
                f"payload_len={len(self.payload)})")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _pad_packet(data: bytes) -> bytes:
    """Pad serialized packet to the smallest allowed size."""
    for s in ALLOWED_SIZES:
        if s >= len(data):
            needed = s - len(data)
            if needed > 0:
                import os
                return data + os.urandom(needed)
            return data
    # Payload too large for standard sizes — no padding
    return data


def serialize_packet(packet: Packet, pad: bool = True,
                     hmac_key: Optional[bytes] = None) -> bytes:
    """Serialize a Packet to bytes with optional padding and HMAC.

    If hmac_key is provided, an HMAC-SHA256 tag (16 bytes) is appended
    AFTER the CRC-16 checksum. CRC detects errors; HMAC detects attacks.
    """
    payload = packet.payload

    header = struct.pack(
        '>H B B H I H',
        MAGIC,
        PROTOCOL_VERSION,
        packet.flags,
        packet.stream_id,
        packet.sequence,
        len(payload),
    )

    crc_val = crc16(header + payload)
    data = header + payload + struct.pack('>H', crc_val)

    if hmac_key:
        hmac_tag = compute_hmac(hmac_key, data)
        data += hmac_tag

    if pad:
        data = _pad_packet(data)

    return data


def deserialize_packet(data: bytes,
                       hmac_key: Optional[bytes] = None) -> Optional[Packet]:
    """Deserialize bytes to a Packet. Returns None if invalid.

    If hmac_key is provided, HMAC is verified in addition to CRC-16.
    CRC catches accidental corruption; HMAC catches malicious tampering.
    """
    min_size = PACKET_OVERHEAD + (HMAC_TAG_SIZE if hmac_key else 0)
    if len(data) < min_size:
        return None

    magic, version, flags, stream_id, seq, payload_len = struct.unpack(
        '>H B B H I H', data[:HEADER_SIZE]
    )

    if magic != MAGIC:
        return None
    if version != PROTOCOL_VERSION:
        return None

    total_needed = HEADER_SIZE + payload_len + CHECKSUM_SIZE
    if hmac_key:
        total_needed += HMAC_TAG_SIZE
    if total_needed > len(data):
        return None

    payload = data[HEADER_SIZE:HEADER_SIZE + payload_len]
    crc_expected = crc16(data[:HEADER_SIZE + payload_len])
    crc_actual = struct.unpack('>H', data[HEADER_SIZE + payload_len:
                                           HEADER_SIZE + payload_len + CHECKSUM_SIZE])[0]

    if crc_expected != crc_actual:
        return None

    # HMAC verification
    if hmac_key:
        hmac_offset = HEADER_SIZE + payload_len + CHECKSUM_SIZE
        hmac_tag = data[hmac_offset:hmac_offset + HMAC_TAG_SIZE]
        signed_data = data[:hmac_offset]
        if not verify_hmac(hmac_key, signed_data, hmac_tag):
            return None  # Tampering detected

    ptype, has_noise, fragmented, is_ack = PacketFlags.unpack(flags)
    return Packet(
        packet_type=ptype,
        stream_id=stream_id,
        sequence=seq,
        payload=payload,
        has_noise=has_noise,
        is_fragmented=fragmented,
        is_ack=is_ack,
    )


# ---------------------------------------------------------------------------
# Packet builders
# ---------------------------------------------------------------------------


def make_negotiate(codebook_ids: list[str], stream_id: int = 0, seq: int = 0) -> Packet:
    """Build a NEGOTIATE packet."""
    import json
    payload = json.dumps({'codebook_ids': codebook_ids}).encode('utf-8')
    return Packet(PacketType.NEGOTIATE, stream_id, seq, payload)


def make_negotiate_ack(codebook_id: str, version: int, session_nonce: bytes,
                       stream_id: int = 0, seq: int = 0,
                       session_timeout: int = 3600,
                       max_packet_size: int = 1024,
                       rotation_interval: int = 1000) -> Packet:
    """Build a NEGOTIATE_ACK packet."""
    import json
    payload = json.dumps({
        'codebook_id': codebook_id,
        'version': version,
        'session_nonce': session_nonce.hex(),
        'session_timeout': session_timeout,
        'max_packet_size': max_packet_size,
        'rotation_interval': rotation_interval,
    }).encode('utf-8')
    return Packet(PacketType.NEGOTIATE_ACK, stream_id, seq, payload)


def make_negotiate_confirm(stream_id: int = 0, seq: int = 0) -> Packet:
    """Build a NEGOTIATE_CONFIRM packet."""
    return Packet(PacketType.NEGOTIATE_CONFIRM, stream_id, seq, b'\x01')


def make_codon(codon_bytes: bytes, stream_id: int = 0, seq: int = 0,
               noise: bytes = b'', fragmented: bool = False,
               chain_index: int = 0) -> Packet:
    """Build a CODON packet.

    Payload format:
      [chain_index: uint16][codon_count: uint8][noise_count: uint8]
      [codons...][noise...]

    chain_index is embedded for sub-chain sync verification.
    """
    import struct
    codon_count = len(codon_bytes) // 3  # rough count — may include param bytes
    noise_count = len(noise) // 3
    payload = (struct.pack('>H B B', chain_index & 0xFFFF, codon_count, noise_count)
               + codon_bytes + noise)
    has_noise = len(noise) > 0
    return Packet(PacketType.CODON, stream_id, seq, payload,
                  has_noise=has_noise, is_fragmented=fragmented)


def make_codon_ack(ack_sequence: int, chain_index: int = 0,
                   stream_id: int = 0, seq: int = 0) -> Packet:
    """Build a CODON ACK packet — acknowledges receipt of a CODON.

    Payload format:
      [chain_index: uint16][ack_sequence: uint32]
    """
    import struct
    payload = struct.pack('>H I', chain_index & 0xFFFF, ack_sequence)
    return Packet(PacketType.CODON, stream_id, seq, payload, is_ack=True)


def make_rotate(new_chain_index: int, stream_id: int = 0, seq: int = 0) -> Packet:
    """Build a ROTATE packet."""
    return Packet(PacketType.ROTATE, stream_id, seq,
                  struct.pack('>I', new_chain_index))


def make_rotate_ack(chain_index: int, stream_id: int = 0, seq: int = 0) -> Packet:
    """Build a ROTATE_ACK packet."""
    return Packet(PacketType.ROTATE_ACK, stream_id, seq,
                  struct.pack('>I', chain_index))


def make_error(error_code: int, detail: str, stream_id: int = 0, seq: int = 0) -> Packet:
    """Build an ERROR packet."""
    detail_bytes = detail.encode('utf-8')
    payload = struct.pack('>H', error_code) + detail_bytes
    return Packet(PacketType.ERROR, stream_id, seq, payload)


def make_fallback(reason: str, stream_id: int = 0, seq: int = 0) -> Packet:
    """Build a FALLBACK packet."""
    return Packet(PacketType.FALLBACK, stream_id, seq, reason.encode('utf-8'))


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------


class ErrorCode:
    CODON_UNKNOWN = 0x1001
    CODON_INVALID = 0x1002
    CODEBOOK_MISMATCH = 0x2001
    SESSION_EXPIRED = 0x3001
    SEQUENCE_INVALID = 0x3002
    SUBCHAIN_MISMATCH = 0x3003
    TRANSPORT_ERROR = 0x4001
    PEER_UNREACHABLE = 0x4002
