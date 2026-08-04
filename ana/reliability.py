"""
Reliability layer for ANA Chain protocol.

Provides CODON ACK tracking, automatic retransmission, PING/PONG
heartbeat-based liveness detection, sub-chain synchronization,
and Bloom filter-based DoS protection.
"""
# Usage:
#     from ana.reliability import ReliableSession
#
#     rs = ReliableSession(session, sock, address)
#     rs.send_codon(codon_bytes)          # auto-ACK-tracked
#     rs.poll()                            # check retransmits + heartbeat
#     event = rs.recv()                    # get next event

import time
import struct
import threading
from dataclasses import dataclass, field
from typing import Optional, Callable

from ana.packet import (
    Packet, PacketType, PacketFlags,
    make_codon, make_codon_ack, make_error, make_rotate,
    serialize_packet, deserialize_packet,
    ErrorCode, HEADER_SIZE, PACKET_OVERHEAD,
)
from ana.codon import (
    CodonEncoder, CodonDecoder,
    NOOP_SERVICE, NOOP_OPERATION, NOOP_TEMPLATE,
    RESERVED_SERVICE, CTRL_PING, CTRL_PONG, CTRL_TEARDOWN,
)
from ana.session import Session, SessionState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_codon_payload(payload: bytes) -> tuple[int, int, int, bytes, bytes]:
    """Parse a CODON packet payload.

    Payload format:
      [chain_index: uint16][codon_count: uint8][noise_count: uint8]
      [real_codons...][noise_codons...]

    Returns (chain_index, codon_count, noise_count, codon_bytes, noise_bytes).
    """
    if len(payload) < 4:
        raise ValueError(f"CODON payload too short: {len(payload)} bytes")
    chain_index, codon_count, noise_count = struct.unpack('>H B B', payload[:4])
    noise_len = noise_count * 3
    body = payload[4:]
    # Noise codons are always 3 bytes each and come at the end.
    # Real codons are everything in between (variable-length due to params).
    if noise_len > 0 and noise_len <= len(body):
        codon_bytes = body[:-noise_len]
        noise_bytes = body[-noise_len:]
    else:
        codon_bytes = body
        noise_bytes = b''
    return chain_index, codon_count, noise_count, codon_bytes, noise_bytes


def make_ping_codon() -> bytes:
    """Create a PING control codon: [0xFF, 0x04, 0x00]."""
    return bytes([RESERVED_SERVICE, CTRL_PING, 0x00])


def make_pong_codon() -> bytes:
    """Create a PONG control codon: [0xFF, 0x05, 0x00]."""
    return bytes([RESERVED_SERVICE, CTRL_PONG, 0x00])


def make_teardown_codon() -> bytes:
    """Create a TEARDOWN control codon: [0xFF, 0x02, 0x00]."""
    return bytes([RESERVED_SERVICE, CTRL_TEARDOWN, 0x00])


# ---------------------------------------------------------------------------
# Event types emitted by ReliableSession
# ---------------------------------------------------------------------------

@dataclass
class CodonEvent:
    """A decoded CODON that was successfully received."""
    codons: list[dict]
    stream_id: int
    sequence: int

@dataclass
class AckEvent:
    """An ACK was received for a previously sent CODON."""
    acked_sequence: int

@dataclass
class PingEvent:
    """A PING was received -- should respond with PONG."""

@dataclass
class PongEvent:
    """A PONG was received -- peer is alive."""

@dataclass
class ErrorEvent:
    """An ERROR packet was received or a local error occurred."""
    code: int
    detail: str

@dataclass
class TimeoutEvent:
    """A CODON was not ACKed within the retransmission window."""
    sequence: int

@dataclass
class PeerDeadEvent:
    """Peer is considered unreachable (heartbeat timeout)."""

@dataclass
class ChainMismatchEvent:
    """Sub-chain mismatch detected -- peer is on a different sub-chain."""
    our_chain: int
    their_chain: int


# ---------------------------------------------------------------------------
# Bloom Filter (DoS protection)
# ---------------------------------------------------------------------------

class BloomFilter:
    """
    Compact probabilistic set for fast codon pre-screening.

    Before performing an expensive anticodon lookup, the receiver
    checks the Bloom filter. Known-valid codon prefixes pass through
    quickly; unknown prefixes are rejected with 99.9% probability
    without ever touching the codebook.

    1 KB of memory -> ~1% false positive rate for 1000 entries.
    """

    def __init__(self, size_bits: int = 8192, hash_count: int = 7):
        """
        Args:
            size_bits: Number of bits in the bit array (default 8192 = 1 KB).
            hash_count: Number of hash functions (default 7, optimal for ~1% FPR).
        """
        self.size = size_bits
        self.hash_count = hash_count
        self.bits = bytearray((size_bits + 7) // 8)

    def _hashes(self, data: bytes):
        """Generate hash_count hashes from data using double hashing."""
        import hashlib
        h = hashlib.sha256(data).digest()
        # Use first 8 bytes as two u32 seeds
        h1 = int.from_bytes(h[:4], 'big')
        h2 = int.from_bytes(h[4:8], 'big')
        for i in range(self.hash_count):
            yield (h1 + i * h2) % self.size

    def add(self, data: bytes):
        """Insert an item into the filter."""
        for pos in self._hashes(data):
            byte_idx = pos // 8
            bit_idx = pos % 8
            self.bits[byte_idx] |= (1 << bit_idx)

    def might_contain(self, data: bytes) -> bool:
        """Check if an item might be in the filter.

        Returns True if the item MAY be present (could be false positive).
        Returns False if the item is DEFINITELY NOT present.
        """
        for pos in self._hashes(data):
            byte_idx = pos // 8
            bit_idx = pos % 8
            if not (self.bits[byte_idx] & (1 << bit_idx)):
                return False
        return True

    @classmethod
    def from_codebook(cls, codebook, size_bits: int = 8192) -> 'BloomFilter':
        """Build a Bloom filter from a codebook known codon prefixes.

        For each (service_id, operation_id, template_id) in the codebook,
        inserts a 3-byte prefix into the filter.
        """
        bf = cls(size_bits=size_bits)
        for svc in codebook.services.values():
            for op in svc.operations:
                for tpl in op.templates:
                    prefix = bytes([svc.id, op.id, tpl.id])
                    bf.add(prefix)
        return bf


# ---------------------------------------------------------------------------
# ACK Tracker
# ---------------------------------------------------------------------------

@dataclass
class _PendingSend:
    data: bytes
    retries: int = 0
    sent_at: float = 0.0
    callback: Optional[Callable] = None


class ACKTracker:
    """Tracks sent CODON packets waiting for acknowledgment."""

    def __init__(self, retransmit_timeout: float = 1.0, max_retransmits: int = 3):
        self.timeout = retransmit_timeout
        self.max_retransmits = max_retransmits
        self._pending: dict[int, _PendingSend] = {}

    def track(self, seq: int, wire_data: bytes):
        """Register a sent packet for ACK tracking."""
        self._pending[seq] = _PendingSend(
            data=wire_data,
            retries=0,
            sent_at=time.time(),
        )

    def ack(self, seq: int) -> bool:
        """Mark a packet as acknowledged. Returns True if it was pending."""
        if seq in self._pending:
            del self._pending[seq]
            return True
        return False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def check(self, send_fn: Callable[[bytes], None]) -> list[TimeoutEvent]:
        """Check for packets needing retransmission.

        Calls send_fn for each retransmission.
        Returns TimeoutEvent for packets that have exhausted retries.
        """
        now = time.time()
        timeouts = []
        for seq, pending in list(self._pending.items()):
            if now - pending.sent_at > self.timeout:
                if pending.retries < self.max_retransmits:
                    send_fn(pending.data)
                    pending.retries += 1
                    pending.sent_at = now
                else:
                    timeouts.append(TimeoutEvent(sequence=seq))
                    del self._pending[seq]
        return timeouts

    def clear(self):
        self._pending.clear()


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

class Heartbeat:
    """Manages PING/PONG liveness detection."""

    def __init__(self, interval: float = 30.0, timeout: float = 90.0):
        self.interval = interval       # send PING every N seconds
        self.timeout = timeout         # consider dead after N seconds of silence
        self.last_sent = time.time()
        self.last_recv = time.time()

    def should_ping(self) -> bool:
        return time.time() - self.last_sent >= self.interval

    def is_dead(self) -> bool:
        return time.time() - self.last_recv >= self.timeout

    def sent(self):
        self.last_sent = time.time()

    def received(self):
        self.last_recv = time.time()


# ---------------------------------------------------------------------------
# ReliableSession
# ---------------------------------------------------------------------------

class ReliableSession:
    """
    Wraps a Session with reliability guarantees:

    - Automatic CODON ACK and retransmission
    - PING/PONG heartbeat for liveness detection
    - Sub-chain index embedded in each CODON for sync verification
    """

    def __init__(self, session: Session, sock, address: tuple[str, int],
                 ack_timeout: float = 1.0, max_retransmits: int = 3,
                 heartbeat_interval: float = 30.0, heartbeat_timeout: float = 90.0):
        self.session = session
        self.sock = sock
        self.address = address
        self._ack_tracker = ACKTracker(ack_timeout, max_retransmits)
        self._heartbeat = Heartbeat(heartbeat_interval, heartbeat_timeout)
        self._send_seq = 0
        # Build Bloom filter for fast DoS-protected codon pre-screening
        if session.codebook:
            self._bloom = BloomFilter.from_codebook(session.codebook)
        else:
            self._bloom = None

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_codon(self, codon_bytes: bytes, stream_id: int = 0,
                   noise: bytes = b'', fragmented: bool = False):
        """Send a CODON packet with automatic ACK tracking, chain_index, and HMAC."""
        seq = self._send_seq
        self._send_seq += 1

        packet = make_codon(
            codon_bytes, stream_id, seq, noise, fragmented,
            chain_index=self.session.current_chain_index,
        )
        wire = serialize_packet(packet, pad=True, hmac_key=self.session.hmac_key)

        self._ack_tracker.track(seq, wire)
        self.sock.sendto(wire, self.address)
        self.session.record_send()

    def send_ack(self, ack_sequence: int, stream_id: int = 0):
        """Send a CODON ACK for a received packet."""
        packet = make_codon_ack(
            ack_sequence,
            chain_index=self.session.current_chain_index,
            stream_id=stream_id,
            seq=self._send_seq,
        )
        self._send_seq += 1
        wire = serialize_packet(packet, pad=True)
        self.sock.sendto(wire, self.address)

    def send_ping(self):
        """Send a PING heartbeat."""
        ping = make_ping_codon()
        self.send_codon(ping)
        self._heartbeat.sent()

    def send_pong(self):
        """Send a PONG response."""
        pong = make_pong_codon()
        self.send_codon(pong)

    def send_rotate(self, new_chain_index: int):
        """Send a ROTATE packet."""
        packet = make_rotate(new_chain_index, stream_id=0, seq=self._send_seq)
        self._send_seq += 1
        wire = serialize_packet(packet, pad=True)
        self._ack_tracker.track(self._send_seq - 1, wire)
        self.sock.sendto(wire, self.address)
        self.session.record_send()

    def send_error(self, error_code: int, detail: str):
        """Send an ERROR packet."""
        packet = make_error(error_code, detail, stream_id=0, seq=self._send_seq)
        self._send_seq += 1
        wire = serialize_packet(packet, pad=True)
        self.sock.sendto(wire, self.address)

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    def recv(self, timeout: Optional[float] = 0.01) -> list:
        """Receive and process incoming packets.

        Returns a list of typed events: CodonEvent, AckEvent, PingEvent,
        PongEvent, ErrorEvent, ChainMismatchEvent, etc.

        Call this in a loop.
        """
        import socket as sock_mod
        events = []

        try:
            self.sock.settimeout(timeout if timeout else 0.01)
            data, addr = self.sock.recvfrom(65535)
        except sock_mod.timeout:
            return events

        packet = deserialize_packet(data, hmac_key=self.session.hmac_key)
        if packet is None:
            # HMAC failure or CRC failure or invalid packet
            return events

        self.session.record_recv()
        self._heartbeat.received()

        # Validate sequence
        if not self.session.check_recv_seq(packet.stream_id, packet.sequence):
            events.append(ErrorEvent(ErrorCode.SEQUENCE_INVALID,
                                     f"sequence {packet.sequence} out of window"))
            return events

        # Handle by packet type
        if packet.is_ack:
            ack_seq = struct.unpack('>I', packet.payload[2:6])[0]  # skip chain_index u16
            self._ack_tracker.ack(ack_seq)
            events.append(AckEvent(acked_sequence=ack_seq))

        elif packet.packet_type == PacketType.CODON:
            chain_idx, codon_count, noise_count, codon_bytes, noise_bytes = \
                parse_codon_payload(packet.payload)

            # Check chain sync
            if chain_idx != self.session.current_chain_index:
                events.append(ChainMismatchEvent(
                    our_chain=self.session.current_chain_index,
                    their_chain=chain_idx,
                ))
                return events

            # Send ACK
            self.send_ack(packet.sequence, packet.stream_id)

            # Decode codons
            decoder = self.session.decoder
            if decoder is None:
                return events

            # Bloom filter pre-screening (DoS protection)
            if self._bloom:
                for i in range(0, len(codon_bytes), 3):
                    prefix = codon_bytes[i:i+3]
                    if len(prefix) == 3 and prefix != b'\x00\x00\x00':
                        if not self._bloom.might_contain(prefix):
                            # Unknown codon prefix -> reject without lookup
                            events.append(ErrorEvent(
                                ErrorCode.CODON_UNKNOWN,
                                f"codon prefix {prefix.hex()} not in codebook"
                            ))
                            return events

            decoded = decoder.decode_multi(codon_bytes)

            # Check for control codons
            for d in decoded:
                if d.get('is_control'):
                    if d.get('control_type') == 'ping':
                        events.append(PingEvent())
                    elif d.get('control_type') == 'pong':
                        events.append(PongEvent())
                    elif d.get('control_type') == 'teardown':
                        self.session.close()
                    continue
                if d.get('is_noise'):
                    continue

            # Filter to real codons
            real = [d for d in decoded if not d.get('is_noise') and not d.get('is_control')
                    and not d.get('is_reserved') and not d.get('error')]
            if real:
                events.append(CodonEvent(
                    codons=real,
                    stream_id=packet.stream_id,
                    sequence=packet.sequence,
                ))

        elif packet.packet_type == PacketType.ERROR:
            code = struct.unpack('>H', packet.payload[:2])[0]
            detail = packet.payload[2:].decode('utf-8', errors='replace')
            events.append(ErrorEvent(code=code, detail=detail))

        elif packet.packet_type == PacketType.ROTATE:
            new_chain = struct.unpack('>I', packet.payload[:4])[0]
            self.session.rotate(new_chain)
            # Send ROTATE_ACK
            from ana.packet import make_rotate_ack
            ack_pkt = make_rotate_ack(new_chain, stream_id=0, seq=self._send_seq)
            self._send_seq += 1
            self.sock.sendto(serialize_packet(ack_pkt, pad=True), self.address)

        elif packet.packet_type == PacketType.ROTATE_ACK:
            chain = struct.unpack('>I', packet.payload[:4])[0]
            # ACK the ROTATE that was tracked
            # (ROTATE was tracked under its send seq)
            pass  # handled by ACK tracker if ROTATE was tracked

        elif packet.packet_type == PacketType.FALLBACK:
            self.session.fallback()

        return events

    # ------------------------------------------------------------------
    # Poll loop -- call frequently
    # ------------------------------------------------------------------

    def poll(self) -> list:
        """
        One tick of the reliability loop. Should be called frequently.

        1. Receives and processes incoming packets
        2. Checks for packets needing retransmission
        3. Checks heartbeat and sends PING if needed
        4. Detects dead peer

        Returns combined list of all events from this tick.
        """
        events = self.recv(timeout=0.01)

        # Retransmit timed-out packets
        def _resend(data: bytes):
            self.sock.sendto(data, self.address)

        timeout_events = self._ack_tracker.check(_resend)
        events.extend(timeout_events)

        # Heartbeat
        if self._heartbeat.should_ping():
            self.send_ping()

        if self._heartbeat.is_dead():
            events.append(PeerDeadEvent())

        return events

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_alive(self) -> bool:
        return (self.session.is_active
                and not self._heartbeat.is_dead()
                and not self.session.is_expired)

    def close(self):
        """Gracefully close the session."""
        teardown = make_teardown_codon()
        self.send_codon(teardown)
        self.session.close()
        self._ack_tracker.clear()
