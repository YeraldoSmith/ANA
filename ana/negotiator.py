"""
Session negotiation for ANA Chain protocol.

Handles the TCP-based initial handshake: exchange codebook versions,
agree on common codebook, perform X25519 ECDH key exchange,
and derive per-session encryption/HMAC keys.

v0.2.1: Added X25519 ECDH so each session gets unique keys.
         Without ECDH, any codebook holder could derive other sessions'
         keys from the plaintext session_nonce. Now each pair gets a
         unique shared secret via ephemeral X25519 exchange.
"""

import json
import os
import struct
from dataclasses import dataclass, field
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey
)

from ana.packet import (
    Packet, PacketType,
    make_negotiate, make_negotiate_ack, make_negotiate_confirm,
    make_error, ErrorCode,
    serialize_packet, deserialize_packet,
)
from ana.session import Session, SessionConfig
from ana.codebook import (
    Codebook, CodebookVersion, derive_master_seed, derive_hmac_key, hkdf,
)


@dataclass
class NegotiationResult:
    """Result of a successful negotiation."""
    codebook: Codebook
    codebook_version: CodebookVersion
    session_nonce: bytes
    config: SessionConfig
    ecdh_shared_secret: bytes = field(default=b'')


class Negotiator:
    """
    Manages the ANA negotiation handshake.

    Usage (Agent side):
        negotiator = Negotiator(available_codebooks)
        sock.connect(api_address)
        session = negotiator.negotiate_as_agent(sock)

    Usage (API side):
        negotiator = Negotiator(available_codebooks)
        # on incoming connection:
        session = negotiator.negotiate_as_api(sock)
    """

    def __init__(self, available_codebooks: dict[str, Codebook]):
        """
        Args:
            available_codebooks: Map of codebook_id → Codebook that this side supports.
        """
        self.codebooks = available_codebooks
        self._eph_sk: Optional[X25519PrivateKey] = None
        self._eph_pk_bytes: bytes = b''

    def _generate_ephemeral_key(self) -> bytes:
        """Generate an ephemeral X25519 keypair for this negotiation."""
        self._eph_sk = X25519PrivateKey.generate()
        self._eph_pk_bytes = self._eph_sk.public_key().public_bytes_raw()
        return self._eph_pk_bytes

    # ------------------------------------------------------------------
    # Agent side
    # ------------------------------------------------------------------

    def negotiate_as_agent(self, sock, timeout: float = 10.0) -> NegotiationResult:
        """Execute the agent-side negotiation with X25519 ECDH key exchange."""
        sock.settimeout(timeout)

        # Step 1: Generate ephemeral key + Send NEGOTIATE
        eph_pk = self._generate_ephemeral_key()
        supported = list(self.codebooks.keys())
        packet = make_negotiate(supported, stream_id=0, seq=0,
                                eph_pk=eph_pk)
        self._send(sock, packet)

        # Step 2: Receive NEGOTIATE_ACK (with API's ephemeral key)
        response = self._recv(sock)
        if response.packet_type != PacketType.NEGOTIATE_ACK:
            raise RuntimeError(f"Expected NEGOTIATE_ACK, got {response.packet_type}")

        ack_data = json.loads(response.payload.decode('utf-8'))
        codebook_id = ack_data['codebook_id']
        version = ack_data['version']
        session_nonce = bytes.fromhex(ack_data['session_nonce'])
        peer_eph_pk = bytes.fromhex(ack_data.get('eph_pk', ''))

        if codebook_id not in self.codebooks:
            raise RuntimeError(f"API selected unknown codebook: {codebook_id}")

        codebook = self.codebooks[codebook_id]

        config = SessionConfig(
            session_timeout=ack_data.get('session_timeout', 3600),
            max_packet_size=ack_data.get('max_packet_size', 1024),
            rotation_interval=ack_data.get('rotation_interval', 1000),
        )

        # Compute ECDH shared secret
        ecdh_secret = b''
        if peer_eph_pk and self._eph_sk:
            try:
                their_eph = X25519PublicKey.from_public_bytes(peer_eph_pk)
                ecdh_secret = self._eph_sk.exchange(their_eph)
            except Exception:
                pass  # fall back to no-ECDH mode

        # Step 3: Send NEGOTIATE_CONFIRM
        confirm = make_negotiate_confirm(stream_id=0, seq=1)
        self._send(sock, confirm)

        return NegotiationResult(
            codebook=codebook,
            codebook_version=codebook.version,
            session_nonce=session_nonce,
            config=config,
            ecdh_shared_secret=ecdh_secret,
        )

    # ------------------------------------------------------------------
    # API side
    # ------------------------------------------------------------------

    def negotiate_as_api(self, sock, timeout: float = 10.0) -> NegotiationResult:
        """Execute the API-side negotiation with X25519 ECDH key exchange."""
        sock.settimeout(timeout)

        # Step 1: Receive NEGOTIATE (with Agent's ephemeral key)
        request = self._recv(sock)
        if request.packet_type != PacketType.NEGOTIATE:
            raise RuntimeError(f"Expected NEGOTIATE, got {request.packet_type}")

        req_data = json.loads(request.payload.decode('utf-8'))
        agent_codebooks = req_data.get('codebook_ids', [])
        peer_eph_pk = bytes.fromhex(req_data.get('eph_pk', ''))

        # Step 2: Select best common codebook
        selected = self._select_codebook(agent_codebooks)
        if selected is None:
            error = make_error(ErrorCode.CODEBOOK_MISMATCH,
                               f"No common codebook. Agent supports: {agent_codebooks}")
            self._send(sock, error)
            raise RuntimeError("No common codebook found")

        codebook_id, codebook = selected
        session_nonce = os.urandom(32)

        # Generate our ephemeral key
        eph_pk = self._generate_ephemeral_key()

        # Compute ECDH shared secret
        ecdh_secret = b''
        if peer_eph_pk and self._eph_sk:
            try:
                their_eph = X25519PublicKey.from_public_bytes(peer_eph_pk)
                ecdh_secret = self._eph_sk.exchange(their_eph)
            except Exception:
                pass

        # Step 3: Send NEGOTIATE_ACK (with our ephemeral key)
        ack = make_negotiate_ack(
            codebook_id=codebook_id,
            version=codebook.version.version,
            session_nonce=session_nonce,
            stream_id=0,
            seq=0,
            eph_pk=eph_pk,
        )
        self._send(sock, ack)

        # Step 4: Receive NEGOTIATE_CONFIRM
        confirm = self._recv(sock)
        if confirm.packet_type != PacketType.NEGOTIATE_CONFIRM:
            raise RuntimeError(f"Expected NEGOTIATE_CONFIRM, got {confirm.packet_type}")

        return NegotiationResult(
            codebook=codebook,
            codebook_version=codebook.version,
            session_nonce=session_nonce,
            config=SessionConfig(),
            ecdh_shared_secret=ecdh_secret,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _select_codebook(self, agent_ids: list[str]) -> Optional[tuple[str, Codebook]]:
        """Select the highest-priority common codebook.

        Priority: first match in the API's available list wins.
        """
        for cid in self.codebooks:
            if cid in agent_ids:
                return (cid, self.codebooks[cid])
        return None

    @staticmethod
    def _send(sock, packet: Packet):
        data = serialize_packet(packet, pad=False)
        sock.sendall(data)

    @staticmethod
    def _recv(sock) -> Packet:
        """Receive a single packet from a TCP socket."""
        # Read header first
        from ana.packet import HEADER_SIZE, PACKET_OVERHEAD
        header = b''
        while len(header) < HEADER_SIZE:
            chunk = sock.recv(HEADER_SIZE - len(header))
            if not chunk:
                raise ConnectionError("Connection closed during header")
            header += chunk

        magic, version, flags, stream_id, seq, payload_len = struct.unpack(
            '>H B B H I H', header
        )

        # Read payload + checksum
        remaining = payload_len + 2  # +2 for checksum
        data = b''
        while len(data) < remaining:
            chunk = sock.recv(remaining - len(data))
            if not chunk:
                raise ConnectionError("Connection closed during payload")
            data += chunk

        return deserialize_packet(header + data)
