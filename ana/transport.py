"""
UDP transport for ANA Chain protocol.

Handles codon packet sending/receiving with noise injection,
fragmentation, and anti-replay checks.
"""

import os
import socket
import struct
import time
from typing import Optional, Callable

from ana.packet import (
    Packet, PacketType,
    make_codon, make_rotate, make_rotate_ack, make_error, make_fallback,
    ErrorCode,
    serialize_packet, deserialize_packet,
    HEADER_SIZE, PACKET_OVERHEAD,
)
from ana.session import Session, SessionState


class NoiseGenerator:
    """Generates noise codons for traffic analysis resistance."""

    def __init__(self, noise_ratio: float = 0.1):
        """
        Args:
            noise_ratio: Fraction of codons that are noise (0.0–0.5).
        """
        self.noise_ratio = max(0.0, min(0.5, noise_ratio))

    def generate(self, real_codon_count: int) -> bytes:
        """Generate noise codon bytes.

        Args:
            real_codon_count: Number of real codons in the payload.

        Returns:
            Noise codons bytes (each noise codon is 3 bytes: 0x000000).
        """
        import random
        noise_count = int(real_codon_count * self.noise_ratio)
        if noise_count == 0 and self.noise_ratio > 0 and real_codon_count > 0:
            noise_count = 1  # always at least 1 noise if ratio > 0
        return b'\x00\x00\x00' * noise_count


class UDPSender:
    """Sends ANA packets over UDP."""

    def __init__(self, session: Session, sock: socket.socket,
                 address: tuple[str, int],
                 noise_gen: Optional[NoiseGenerator] = None):
        self.session = session
        self.sock = sock
        self.address = address
        self.noise_gen = noise_gen or NoiseGenerator(noise_ratio=0.0)

    def send_codon(self, codon_bytes: bytes, stream_id: int = 0,
                   fragmented: bool = False) -> int:
        """Send a CODON packet.

        Returns the sequence number used (for matching responses).
        """
        if not self.session.is_active:
            raise RuntimeError(f"Session not active: {self.session.state}")

        seq = self.session.next_send_seq(stream_id)

        # Generate noise
        noise = b''
        if self.noise_gen.noise_ratio > 0:
            codon_count = max(1, len(codon_bytes) // 3)
            noise = self.noise_gen.generate(codon_count)

        packet = make_codon(codon_bytes, stream_id, seq, noise, fragmented)
        data = serialize_packet(packet, pad=True)
        self.sock.sendto(data, self.address)
        self.session.record_send()

        return seq

    def send_rotate(self, new_chain_index: int, stream_id: int = 0) -> int:
        """Send a ROTATE packet."""
        seq = self.session.next_send_seq(stream_id)
        packet = make_rotate(new_chain_index, stream_id, seq)
        self.sock.sendto(serialize_packet(packet, pad=True), self.address)
        self.session.record_send()
        return seq

    def send_error(self, error_code: int, detail: str, stream_id: int = 0):
        """Send an ERROR packet."""
        seq = self.session.next_send_seq(stream_id)
        packet = make_error(error_code, detail, stream_id, seq)
        self.sock.sendto(serialize_packet(packet, pad=True), self.address)
        self.session.record_send()

    def send_fallback(self, reason: str = "manual", stream_id: int = 0):
        """Send a FALLBACK packet and transition session to fallback."""
        seq = self.session.next_send_seq(stream_id)
        packet = make_fallback(reason, stream_id, seq)
        self.sock.sendto(serialize_packet(packet, pad=True), self.address)
        self.session.record_send()
        self.session.fallback()


class UDPReceiver:
    """Receives ANA packets over UDP."""

    def __init__(self, session: Session, sock: socket.socket,
                 noise_gen: Optional[NoiseGenerator] = None):
        self.session = session
        self.sock = sock
        self.noise_gen = noise_gen

    def recv(self, timeout: Optional[float] = None) -> Optional[Packet]:
        """Receive and validate a single ANA packet.

        Returns None on timeout or invalid packet.
        """
        if timeout is not None:
            self.sock.settimeout(timeout)

        try:
            data, addr = self.sock.recvfrom(65535)
        except socket.timeout:
            return None

        packet = deserialize_packet(data)
        if packet is None:
            return None  # Invalid magic, version, or checksum

        # Validate sequence (anti-replay)
        if not self.session.check_recv_seq(packet.stream_id, packet.sequence):
            return None  # Replay detected

        self.session.record_recv()

        # Handle control packets
        if packet.packet_type == PacketType.ROTATE:
            chain_index = struct.unpack('>I', packet.payload[:4])[0]
            self.session.rotate(chain_index)
        elif packet.packet_type == PacketType.ERROR:
            code = struct.unpack('>H', packet.payload[:2])[0]
            detail = packet.payload[2:].decode('utf-8', errors='replace')
            # Let caller decide how to handle
        elif packet.packet_type == PacketType.FALLBACK:
            self.session.fallback()

        return packet
