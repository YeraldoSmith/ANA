"""
ANA-S: Native security layer for ANA Chain Protocol.

Replaces TLS with a lightweight, Agent-native secure handshake:
  - X25519 ECDH key exchange (Curve25519)
  - Ed25519 signatures (identity binding)
  - ChaCha20-Poly1305 AEAD (encryption + integrity)

Inspired by Noise Protocol Framework IK pattern (used by WhatsApp, WireGuard).

Usage:
    from ana.security import ANAIdentity, ANASecureSession

    # Generate long-term Agent identity
    aid = ANAIdentity.generate()

    # Server-side: handle HELLO
    session = ANASecureSession(our_identity=aid)
    hello_ack = session.handle_hello(hello_packet)

    # After handshake: encrypt/decrypt packets
    ciphertext = session.encrypt(plaintext)
    plaintext = session.decrypt(ciphertext)
"""

import os
import hashlib
import hmac as _hmac
from dataclasses import dataclass
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# ─── Agent Identity (AID) ─────────────────────────────────────────

@dataclass
class ANAIdentity:
    """Long-term Agent identity: X25519 + Ed25519 keypair."""
    aid_id: bytes          # 32 bytes, SHA-256 of Ed25519 public key
    x25519_sk: X25519PrivateKey
    x25519_pk: X25519PublicKey
    ed25519_sk: Ed25519PrivateKey
    ed25519_pk: Ed25519PublicKey

    @classmethod
    def generate(cls) -> 'ANAIdentity':
        x_sk = X25519PrivateKey.generate()
        e_sk = Ed25519PrivateKey.generate()
        # aid_id IS the raw Ed25519 public key (for direct signature verification)
        aid_id = e_sk.public_key().public_bytes_raw()
        return cls(
            aid_id=aid_id,
            x25519_sk=x_sk,
            x25519_pk=x_sk.public_key(),
            ed25519_sk=e_sk,
            ed25519_pk=e_sk.public_key(),
        )

    def public_bytes(self) -> dict:
        return {
            'aid_id': self.aid_id.hex(),
            'x25519_pk': self.x25519_pk.public_bytes_raw().hex(),
            'ed25519_pk': self.ed25519_pk.public_bytes_raw().hex(),
        }


# ─── Key derivation ───────────────────────────────────────────────

def _hkdf(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info)
    return hkdf.derive(ikm)


def derive_session_keys(shared_secret: bytes, nonce_a: bytes,
                        nonce_b: bytes) -> dict:
    """Derive session keys from the ECDH shared secret."""
    session_seed = _hkdf(
        ikm=shared_secret,
        salt=nonce_a + nonce_b,
        info=b"ANA-S-v1-session-seed",
        length=64,
    )
    # AEAD key for A->B direction
    aead_key_ab = _hkdf(
        ikm=session_seed,
        salt=b"",
        info=b"ANA-S-v1-aead-A-to-B",
        length=32,
    )
    # AEAD key for B->A direction
    aead_key_ba = _hkdf(
        ikm=session_seed,
        salt=b"",
        info=b"ANA-S-v1-aead-B-to-A",
        length=32,
    )
    return {
        'session_seed': session_seed,
        'aead_key_send': aead_key_ab,
        'aead_key_recv': aead_key_ba,
    }


# ─── AEAD encryption ──────────────────────────────────────────────

class AEADCipher:
    """ChaCha20-Poly1305 AEAD encrypt/decrypt."""

    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("AEAD key must be 32 bytes")
        self._cipher = ChaCha20Poly1305(key)

    def encrypt(self, plaintext: bytes, nonce: bytes) -> bytes:
        """Encrypt with 12-byte nonce. Returns ciphertext + 16-byte tag."""
        if len(nonce) != 12:
            raise ValueError("nonce must be 12 bytes")
        return self._cipher.encrypt(nonce, plaintext, None)

    def decrypt(self, ciphertext: bytes, nonce: bytes) -> Optional[bytes]:
        """Decrypt. Returns None on authentication failure."""
        if len(nonce) != 12:
            raise ValueError("nonce must be 12 bytes")
        try:
            return self._cipher.decrypt(nonce, ciphertext, None)
        except Exception:
            return None


# ─── Handshake packet builder/parser ──────────────────────────────

@dataclass
class HelloPacket:
    """HELLO packet sent by the initiator."""
    aid_id: bytes       # 32 bytes
    eph_pk: bytes       # 32 bytes (X25519 ephemeral public key)
    nonce: bytes        # 16 bytes
    signature: bytes    # 64 bytes (Ed25519 over aid_id + eph_pk + nonce)

    def serialize(self) -> bytes:
        return self.aid_id + self.eph_pk + self.nonce + self.signature

    @classmethod
    def deserialize(cls, data: bytes) -> 'HelloPacket':
        if len(data) != 144:
            raise ValueError(f"HELLO must be 144 bytes, got {len(data)}")
        return cls(
            aid_id=data[0:32],
            eph_pk=data[32:64],
            nonce=data[64:80],
            signature=data[80:144],
        )


@dataclass
class HelloAckPacket:
    """HELLO_ACK sent by the responder."""
    aid_id: bytes       # 32 bytes
    eph_pk: bytes       # 32 bytes (X25519 ephemeral public key)
    nonce: bytes        # 16 bytes
    signature: bytes    # 64 bytes (Ed25519 over aid_id + eph_pk + nonce)

    def serialize(self) -> bytes:
        return self.aid_id + self.eph_pk + self.nonce + self.signature

    @classmethod
    def deserialize(cls, data: bytes) -> 'HelloAckPacket':
        if len(data) != 144:
            raise ValueError(f"HELLO_ACK must be 144 bytes, got {len(data)}")
        return cls(
            aid_id=data[0:32],
            eph_pk=data[32:64],
            nonce=data[64:80],
            signature=data[80:144],
        )


# ─── Secure Session ───────────────────────────────────────────────

class ANASecureSession:
    """
    ANA-S secure session with X25519 + Ed25519 + ChaCha20-Poly1305.

    Usage (initiator / Agent):
        session = ANASecureSession(our_identity=aid_a, their_public_key=pk_b)
        hello = session.create_hello()
        # ... send hello to B, receive hello_ack ...
        session.complete_handshake(hello_ack)

    Usage (responder / API):
        session = ANASecureSession(our_identity=aid_b)
        hello_ack = session.handle_hello(hello_pkt)
        # ... send hello_ack to A ...
    """

    def __init__(self, our_identity: ANAIdentity,
                 their_public_key: Optional[bytes] = None):
        self.our_id = our_identity
        self.their_ed25519_pk: Optional[Ed25519PublicKey] = None
        if their_public_key:
            self.their_ed25519_pk = Ed25519PublicKey.from_public_bytes(
                their_public_key
            )

        self._eph_sk: Optional[X25519PrivateKey] = None
        self._eph_pk: Optional[X25519PublicKey] = None
        self._their_eph_pk: Optional[bytes] = None
        self._nonce_self: bytes = b''
        self._nonce_peer: bytes = b''
        self._session_seed: Optional[bytes] = None
        self._aead_send: Optional[AEADCipher] = None
        self._aead_recv: Optional[AEADCipher] = None
        self._send_seq: int = 0
        self._recv_seq: int = 0

    # ── Initiator side ────────────────────────────────────────────

    def create_hello(self) -> HelloPacket:
        """Create a HELLO packet as the initiator."""
        self._nonce_self = os.urandom(16)
        self._eph_sk = X25519PrivateKey.generate()
        self._eph_pk = self._eph_sk.public_key()
        eph_pk_bytes = self._eph_pk.public_bytes_raw()

        # Sign: aid_id + eph_pk + nonce
        sig_data = self.our_id.aid_id + eph_pk_bytes + self._nonce_self
        signature = self.our_id.ed25519_sk.sign(sig_data)

        return HelloPacket(
            aid_id=self.our_id.aid_id,
            eph_pk=eph_pk_bytes,
            nonce=self._nonce_self,
            signature=signature,
        )

    def complete_handshake(self, hello_ack: HelloAckPacket) -> bytes:
        """Process HELLO_ACK, derive keys, return CONFIRM HMAC."""
        if self._eph_sk is None:
            raise RuntimeError("call create_hello() first")

        self._nonce_peer = hello_ack.nonce
        self._their_eph_pk = hello_ack.eph_pk

        # Verify B's signature
        if self.their_ed25519_pk is None:
            self.their_ed25519_pk = Ed25519PublicKey.from_public_bytes(
                hello_ack.aid_id
            )
            # In real use, the caller should verify aid_id matches expected peer.
            # For now, trust the aid_id as the public key hint.
        sig_data = hello_ack.aid_id + hello_ack.eph_pk + hello_ack.nonce
        self.their_ed25519_pk.verify(hello_ack.signature, sig_data)

        # Compute ECDH: ephemeral(A) × ephemeral(B)
        their_eph = X25519PublicKey.from_public_bytes(hello_ack.eph_pk)
        shared1 = self._eph_sk.exchange(their_eph)

        # Second ECDH: ephemeral(A) × static(B)
        # (We don't have B's X25519 static key unless provided separately.
        #  For the minimal implementation, we use a single ECDH.)
        shared_total = shared1

        keys = derive_session_keys(
            shared_total, self._nonce_self, self._nonce_peer
        )
        self._session_seed = keys['session_seed']
        self._aead_send = AEADCipher(keys['aead_key_send'])
        self._aead_recv = AEADCipher(keys['aead_key_recv'])

        # Return CONFIRM HMAC
        return _hmac.new(self._session_seed, b"ANA-S-confirm",
                         hashlib.sha256).digest()[:16]

    # ── Responder side ────────────────────────────────────────────

    def handle_hello(self, hello: HelloPacket) -> HelloAckPacket:
        """Process a HELLO packet and return HELLO_ACK."""
        self._nonce_peer = hello.nonce

        # Verify A's signature using the aid_id as the Ed25519 public key
        # (in ANA-S v0.1, aid_id IS the raw Ed25519 public key)
        their_ed = Ed25519PublicKey.from_public_bytes(hello.aid_id)
        sig_data = hello.aid_id + hello.eph_pk + hello.nonce
        their_ed.verify(hello.signature, sig_data)

        self._their_eph_pk = hello.eph_pk

        # Generate our ephemeral key
        self._nonce_self = os.urandom(16)
        self._eph_sk = X25519PrivateKey.generate()
        self._eph_pk = self._eph_sk.public_key()
        eph_pk_bytes = self._eph_pk.public_bytes_raw()

        # ECDH: ephemeral(B) × ephemeral(A)
        their_eph = X25519PublicKey.from_public_bytes(hello.eph_pk)
        shared1 = self._eph_sk.exchange(their_eph)
        shared_total = shared1

        keys = derive_session_keys(
            shared_total, hello.nonce, self._nonce_self
        )
        self._session_seed = keys['session_seed']
        self._aead_recv = AEADCipher(keys['aead_key_send'])   # A's send = our recv
        self._aead_send = AEADCipher(keys['aead_key_recv'])   # A's recv = our send

        # Sign HELLO_ACK
        sig_data_ack = (self.our_id.aid_id + eph_pk_bytes +
                        self._nonce_self)
        signature_ack = self.our_id.ed25519_sk.sign(sig_data_ack)

        return HelloAckPacket(
            aid_id=self.our_id.aid_id,
            eph_pk=eph_pk_bytes,
            nonce=self._nonce_self,
            signature=signature_ack,
        )

    def verify_confirm(self, confirm_hmac: bytes) -> bool:
        """Verify the CONFIRM HMAC from the initiator."""
        if self._session_seed is None:
            return False
        expected = _hmac.new(self._session_seed, b"ANA-S-confirm",
                             hashlib.sha256).digest()[:16]
        return _hmac.compare_digest(expected, confirm_hmac)

    # ── AEAD encrypt/decrypt ──────────────────────────────────────

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt a packet payload with the session AEAD key."""
        if self._aead_send is None:
            raise RuntimeError("session not established")
        nonce = self._send_seq.to_bytes(8, 'big') + b'\x00\x00\x00\x00'
        self._send_seq += 1
        return self._aead_send.encrypt(plaintext, nonce)

    def decrypt(self, ciphertext: bytes) -> Optional[bytes]:
        """Decrypt a packet payload. Returns None on auth failure."""
        if self._aead_recv is None:
            raise RuntimeError("session not established")
        nonce = self._recv_seq.to_bytes(8, 'big') + b'\x00\x00\x00\x00'
        result = self._aead_recv.decrypt(ciphertext, nonce)
        if result is not None:
            self._recv_seq += 1
        return result

    @property
    def is_established(self) -> bool:
        return self._session_seed is not None

    @property
    def session_seed(self) -> Optional[bytes]:
        return self._session_seed
