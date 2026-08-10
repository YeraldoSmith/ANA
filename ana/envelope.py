"""Strict, transport-independent ANA call envelope.

The human-friendly ``@service.operation.template`` form is useful for LLM
output, but is intentionally not the wire format.  This module binds binary
codon bytes to an exact codebook fingerprint and adds request semantics that
survive retries and transport changes.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import ClassVar


MAGIC = b"ANA3"
WIRE_VERSION = 1
FIRE_AND_FORGET = 1 << 0
KNOWN_FLAGS = FIRE_AND_FORGET
HEADER_SIZE = 4 + 1 + 1 + 32 + 16 + 4 + 2


@dataclass(frozen=True)
class CallEnvelope:
    """One ANA call bound to a particular codebook contract.

    ``request_id`` is caller-generated and stable across retries.  A deadline
    of zero means no protocol-level deadline; transports may still impose one.
    """

    codebook_hash: bytes
    request_id: bytes
    codon: bytes
    deadline_ms: int = 0
    flags: int = 0

    _MAX_CODON_BYTES: ClassVar[int] = 0xFFFF

    def __post_init__(self):
        if len(self.codebook_hash) != 32:
            raise ValueError("codebook_hash must be 32 bytes")
        if len(self.request_id) != 16:
            raise ValueError("request_id must be 16 bytes")
        if not self.codon:
            raise ValueError("codon payload must not be empty")
        if len(self.codon) > self._MAX_CODON_BYTES:
            raise ValueError("codon payload exceeds 65535 bytes")
        if not 0 <= self.deadline_ms <= 0xFFFFFFFF:
            raise ValueError("deadline_ms must fit uint32")
        if not 0 <= self.flags <= 0xFF:
            raise ValueError("flags must fit uint8")
        if self.flags & ~KNOWN_FLAGS:
            raise ValueError("envelope contains reserved flags")

    @classmethod
    def for_codebook(cls, codebook, codon: bytes, *, deadline_ms: int = 0,
                     request_id: bytes | None = None, flags: int = 0) -> 'CallEnvelope':
        """Create an envelope using the codebook's canonical fingerprint."""
        return cls(
            codebook_hash=codebook.content_hash,
            request_id=request_id if request_id is not None else os.urandom(16),
            codon=codon,
            deadline_ms=deadline_ms,
            flags=flags,
        )

    def serialize(self) -> bytes:
        """Encode exactly one envelope; no padding or trailing bytes are allowed."""
        header = struct.pack(
            '>4sBB32s16sIH',
            MAGIC,
            WIRE_VERSION,
            self.flags,
            self.codebook_hash,
            self.request_id,
            self.deadline_ms,
            len(self.codon),
        )
        return header + self.codon

    @classmethod
    def deserialize(cls, data: bytes) -> 'CallEnvelope':
        """Decode an envelope and reject unknown versions and trailing bytes."""
        if len(data) < HEADER_SIZE:
            raise ValueError("truncated ANA call envelope")
        magic, version, flags, codebook_hash, request_id, deadline_ms, codon_len = struct.unpack(
            '>4sBB32s16sIH', data[:HEADER_SIZE]
        )
        if magic != MAGIC:
            raise ValueError("invalid ANA call envelope magic")
        if version != WIRE_VERSION:
            raise ValueError(f"unsupported ANA call envelope version: {version}")
        if len(data) != HEADER_SIZE + codon_len:
            raise ValueError("invalid ANA call envelope length")
        return cls(codebook_hash, request_id, data[HEADER_SIZE:], deadline_ms, flags)

    def verify_codebook(self, codebook) -> None:
        """Fail closed when a peer used a different codebook definition."""
        if self.codebook_hash != codebook.content_hash:
            raise ValueError("codebook fingerprint mismatch")
