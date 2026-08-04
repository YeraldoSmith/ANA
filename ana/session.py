"""
Session state machine for ANA Chain protocol.

Manages the lifecycle: DISCONNECTED → NEGOTIATING → ACTIVE → ROTATING → FALLBACK → CLOSED
"""

import enum
import time
import struct
from dataclasses import dataclass, field
from typing import Optional

from ana.codebook import (
    Codebook, CodebookVersion, derive_master_seed, derive_subchain_seed,
    derive_hmac_key, hkdf,
)
from ana.codon import CodonEncoder, CodonDecoder


class SessionState(enum.Enum):
    DISCONNECTED = "disconnected"
    NEGOTIATING = "negotiating"
    ACTIVE = "active"
    ROTATING = "rotating"
    FALLBACK = "fallback"
    CLOSED = "closed"


@dataclass
class SessionConfig:
    """Session parameters agreed during negotiation."""
    session_timeout: int = 3600         # seconds
    max_packet_size: int = 1024         # bytes
    rotation_interval: int = 1000       # packets per sub-chain


class Session:
    """
    ANA Chain session.

    Holds the negotiated codebook, encoder/decoder, and sequence state.
    Both agent and API sides use the same Session class.
    """

    def __init__(self, side: str = "agent"):
        """
        Args:
            side: "agent" or "api"
        """
        if side not in ("agent", "api"):
            raise ValueError("side must be 'agent' or 'api'")
        self.side = side
        self.state = SessionState.DISCONNECTED

        # Negotiation results
        self.codebook: Optional[Codebook] = None
        self.codebook_version: Optional[CodebookVersion] = None
        self.session_nonce: Optional[bytes] = None
        self.config = SessionConfig()

        # Derived secrets
        self.master_seed: Optional[bytes] = None
        self._subchain_seeds: dict[int, bytes] = {}
        self.current_chain_index: int = 0

        # Sequence tracking
        self._send_seq: dict[int, int] = {}   # stream_id → next send seq
        self._recv_seq: dict[int, int] = {}   # stream_id → last recv seq
        self._replay_window: int = 100         # accept offset within ±window

        # Encoder / Decoder
        self.encoder: Optional[CodonEncoder] = None
        self.decoder: Optional[CodonDecoder] = None

        # HMAC (optional integrity protection)
        self.hmac_key: Optional[bytes] = None
        self.hmac_enabled: bool = False

        # Stats
        self.packets_sent: int = 0
        self.packets_recv: int = 0
        self.current_chain_packets: int = 0
        self.created_at: float = time.time()
        self.last_active: float = time.time()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_negotiation(self):
        """Transition to negotiating state."""
        if self.state not in (SessionState.DISCONNECTED, SessionState.FALLBACK):
            raise RuntimeError(f"Cannot negotiate from state {self.state}")
        self.state = SessionState.NEGOTIATING

    def establish(self, codebook: Codebook, codebook_version: CodebookVersion,
                  session_nonce: bytes, config: Optional[SessionConfig] = None,
                  ecdh_secret: bytes = b''):
        """Establish the session with negotiated parameters.

        If ecdh_secret is provided (from X25519 ECDH during negotiation),
        it is mixed into the HMAC key derivation so each session gets a
        unique key that other codebook holders cannot derive.
        """
        self.codebook = codebook
        self.codebook_version = codebook_version
        self.session_nonce = session_nonce
        if config:
            self.config = config

        # Derive master seed
        self.master_seed = derive_master_seed(
            codebook_version.seed_hash,
            session_nonce,
        )

        # Initialize sub-chain 0
        self._subchain_seeds = {}
        self.current_chain_index = 0
        self._derive_subchain(0)

        # Set up encoder/decoder
        self.encoder = CodonEncoder(codebook)
        self.decoder = CodonDecoder(codebook)

        # HMAC is enabled by default (CAP_HMAC). Derive key with ECDH
        # secret mixed in for per-session uniqueness.
        self.hmac_enabled = True
        hmac_base = self.master_seed
        if ecdh_secret:
            # Mix ECDH shared secret into HMAC key material.
            # Even if another codebook holder sees the session_nonce,
            # they cannot derive our HMAC key without the ECDH secret.
            hmac_base = hkdf(
                salt=ecdh_secret,
                ikm=self.master_seed,
                info=b"ANA-v1-hmac-ecdh",
                length=64,
            )
        self.hmac_key = derive_hmac_key(hmac_base, 0)

        self.state = SessionState.ACTIVE
        self.last_active = time.time()

    def rotate(self, new_chain_index: int):
        """Transition to a new sub-chain."""
        if self.state != SessionState.ACTIVE:
            raise RuntimeError(f"Cannot rotate from state {self.state}")
        self.state = SessionState.ROTATING
        self.current_chain_index = new_chain_index
        self.current_chain_packets = 0
        self._derive_subchain(new_chain_index)
        # Derive new HMAC key for the new sub-chain
        if self.hmac_enabled and self.master_seed:
            self.hmac_key = derive_hmac_key(self.master_seed, new_chain_index)
        self.state = SessionState.ACTIVE

    def fallback(self):
        """Switch to JSON fallback mode."""
        self.state = SessionState.FALLBACK

    def recover_from_fallback(self, codebook: Codebook, codebook_version: CodebookVersion,
                               session_nonce: bytes):
        """Re-establish codon mode after a fallback."""
        self.establish(codebook, codebook_version, session_nonce)

    def close(self):
        """Close the session."""
        self.state = SessionState.CLOSED

    @property
    def is_active(self) -> bool:
        return self.state == SessionState.ACTIVE

    @property
    def is_expired(self) -> bool:
        if self.state == SessionState.CLOSED:
            return True
        elapsed = time.time() - self.last_active
        return elapsed > self.config.session_timeout

    # ------------------------------------------------------------------
    # Sequence tracking
    # ------------------------------------------------------------------

    def next_send_seq(self, stream_id: int = 0) -> int:
        """Get and increment the next send sequence number for a stream."""
        seq = self._send_seq.get(stream_id, 0)
        self._send_seq[stream_id] = seq + 1
        return seq

    def check_recv_seq(self, stream_id: int, seq: int) -> bool:
        """Validate a received sequence number (anti-replay).

        Accepts sequence numbers > last seen, or within a small window
        below last seen (to handle reordering).
        """
        last = self._recv_seq.get(stream_id, -1)
        if seq > last:
            self._recv_seq[stream_id] = seq
            return True
        if seq > last - self._replay_window:
            # Within reorder window — don't update last_seen
            return True
        return False  # Replay detected

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def record_send(self):
        self.packets_sent += 1
        self.current_chain_packets += 1
        self.last_active = time.time()

    def record_recv(self):
        self.packets_recv += 1
        self.last_active = time.time()

    def needs_rotation(self) -> bool:
        """Check if sub-chain rotation is due."""
        return self.current_chain_packets >= self.config.rotation_interval

    def check_chain_sync(self, peer_chain_index: int) -> bool:
        """Verify that the peer's chain_index matches ours.

        Returns True if in sync, False if mismatch detected.
        """
        return peer_chain_index == self.current_chain_index

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _derive_subchain(self, index: int):
        """Derive and cache a sub-chain seed."""
        if index not in self._subchain_seeds:
            self._subchain_seeds[index] = derive_subchain_seed(
                self.master_seed, index
            )

    def get_subchain_seed(self, index: Optional[int] = None) -> bytes:
        """Get the seed for a sub-chain."""
        if index is None:
            index = self.current_chain_index
        if index not in self._subchain_seeds:
            self._derive_subchain(index)
        return self._subchain_seeds[index]

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict:
        return {
            'side': self.side,
            'state': self.state.value,
            'codebook': self.codebook_version.codebook_id if self.codebook_version else None,
            'version': self.codebook_version.version if self.codebook_version else None,
            'chain_index': self.current_chain_index,
            'packets_sent': self.packets_sent,
            'packets_recv': self.packets_recv,
            'chain_packets': self.current_chain_packets,
            'uptime': time.time() - self.created_at,
        }
