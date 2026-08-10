"""
Codebook: the shared mapping from codon IDs to API operations.

A codebook is a hierarchical lookup structure:
  Service → Operation → ParameterTemplate

Codebooks are generated deterministically from a seed using HKDF,
so they never need to be stored or transmitted in full.
"""

import hashlib
import hmac
import json
import struct
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TemplateDef:
    """A parameter template within an operation."""
    id: int
    description: str
    params: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    defaults: dict = field(default_factory=dict)


@dataclass
class OperationDef:
    """An operation within a service."""
    id: int
    name: str
    templates: list[TemplateDef] = field(default_factory=list)


@dataclass
class ServiceDef:
    """A service within a codebook."""
    id: int
    name: str
    operations: list[OperationDef] = field(default_factory=list)


@dataclass
class CodebookVersion:
    """Identifies a specific codebook version."""
    codebook_id: str
    version: int
    seed_hash: bytes       # SHA-256
    capabilities: int = 0  # bitmask
    content_hash: bytes = b''  # SHA-256 of the canonical codebook definition

    CAP_CODON = 1 << 0
    CAP_NOISE = 1 << 1
    CAP_FRAGMENT = 1 << 2
    CAP_ROTATE = 1 << 3

    def to_dict(self) -> dict:
        result = {
            'codebook_id': self.codebook_id,
            'version': self.version,
            'seed_hash': self.seed_hash.hex(),
            'capabilities': self.capabilities,
        }
        if self.content_hash:
            result['content_hash'] = self.content_hash.hex()
        return result

    @classmethod
    def from_dict(cls, d: dict) -> 'CodebookVersion':
        return cls(
            codebook_id=d['codebook_id'],
            version=d['version'],
            seed_hash=bytes.fromhex(d['seed_hash']),
            capabilities=d.get('capabilities', 0),
            content_hash=bytes.fromhex(d['content_hash']) if d.get('content_hash') else b'',
        )


# ---------------------------------------------------------------------------
# HKDF implementation (RFC 5869)
# ---------------------------------------------------------------------------

def _hkdf_extract(salt: bytes, ikm: bytes) -> bytes:
    """HKDF-Extract: PRK = HMAC-Hash(salt, ikm)"""
    if not salt:
        salt = b'\x00' * 32
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand: OKM = T(1) || T(2) || ..."""
    hash_len = 32
    n = (length + hash_len - 1) // hash_len
    t = b""
    okm = b""
    for i in range(1, n + 1):
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
    return okm[:length]


def hkdf(salt: bytes, ikm: bytes, info: bytes, length: int = 64) -> bytes:
    """Full HKDF: Extract-then-Expand."""
    prk = _hkdf_extract(salt, ikm)
    return _hkdf_expand(prk, info, length)


# ---------------------------------------------------------------------------
# Deterministic RNG (ChaCha20-based keystream)
# ---------------------------------------------------------------------------

def _u32(v: bytes, offset: int = 0) -> int:
    return struct.unpack_from('<I', v, offset)[0]


def _rotl(v: int, c: int) -> int:
    return ((v << c) | (v >> (32 - c))) & 0xFFFFFFFF


def _qr(x: list, a: int, b: int, c: int, d: int):
    """ChaCha quarter round."""
    x[a] = (x[a] + x[b]) & 0xFFFFFFFF
    x[d] = _rotl(x[d] ^ x[a], 16)
    x[c] = (x[c] + x[d]) & 0xFFFFFFFF
    x[b] = _rotl(x[b] ^ x[c], 12)
    x[a] = (x[a] + x[b]) & 0xFFFFFFFF
    x[d] = _rotl(x[d] ^ x[a], 8)
    x[c] = (x[c] + x[d]) & 0xFFFFFFFF
    x[b] = _rotl(x[b] ^ x[c], 7)


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    """Generate one 64-byte ChaCha20 block."""
    constants = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
    key_words = list(struct.unpack_from('<IIIIIIII', key))
    counter_nonce = struct.unpack_from('<III', nonce)

    state = constants + key_words + [counter] + list(counter_nonce)
    working = state[:]
    for _ in range(10):
        _qr(working, 0, 4, 8, 12)
        _qr(working, 1, 5, 9, 13)
        _qr(working, 2, 6, 10, 14)
        _qr(working, 3, 7, 11, 15)
        _qr(working, 0, 5, 10, 15)
        _qr(working, 1, 6, 11, 12)
        _qr(working, 2, 7, 8, 13)
        _qr(working, 3, 4, 9, 14)

    output = []
    for i in range(16):
        val = (working[i] + state[i]) & 0xFFFFFFFF
        output.append(struct.pack('<I', val))
    return b''.join(output)


class ChaCha20RNG:
    """Deterministic random byte stream from a ChaCha20 key & nonce."""

    def __init__(self, seed: bytes):
        if len(seed) < 32:
            seed = hashlib.sha256(seed).digest()
        self.key = seed[:32]
        self.nonce = seed[:12] if len(seed) >= 44 else (b'\x00' * 4 + seed[:8])
        self.counter = 0
        self._buffer = b''
        self._pos = 0

    def _refill(self):
        self._buffer = _chacha20_block(self.key, self.counter, self.nonce)
        self.counter += 1
        self._pos = 0

    def randbytes(self, n: int) -> bytes:
        result = bytearray()
        while len(result) < n:
            if self._pos >= len(self._buffer):
                self._refill()
            take = min(n - len(result), len(self._buffer) - self._pos)
            result.extend(self._buffer[self._pos:self._pos + take])
            self._pos += take
        return bytes(result)

    def randint(self, lo: int, hi: int) -> int:
        """Random integer in [lo, hi]."""
        if lo == hi:
            return lo
        span = hi - lo
        # rejection sampling for uniformity
        bytes_needed = (span.bit_length() + 7) // 8
        while True:
            raw = self.randbytes(bytes_needed)
            val = int.from_bytes(raw, 'big')
            if val <= (256 ** bytes_needed) // (span + 1) * (span + 1) - 1:
                return lo + (val % (span + 1))


# ---------------------------------------------------------------------------
# Codebook
# ---------------------------------------------------------------------------


class Codebook:
    """
    A hierarchical mapping from codon IDs to API operation signatures.

    Generated deterministically from a seed so the full codebook
    is never stored or transmitted.
    """

    def __init__(self, version: CodebookVersion, services: list[ServiceDef]):
        self.version = version
        self.services: dict[int, ServiceDef] = {}
        for svc in services:
            self._index_service(svc)

    def _index_service(self, svc: ServiceDef):
        """Build fast lookup indices for a service."""
        self.services[svc.id] = svc
        for op in svc.operations:
            op._templates = {t.id: t for t in op.templates}
        svc._operations = {op.id: op for op in svc.operations}

    # -- lookup helpers --

    def resolve(self, service_id: int, op_id: int, template_id: int):
        """Resolve a codon to its (ServiceDef, OperationDef, TemplateDef)."""
        svc = self.services.get(service_id)
        if svc is None:
            raise KeyError(f"Service {service_id} not found in codebook {self.version.codebook_id}")
        op = svc._operations.get(op_id)
        if op is None:
            raise KeyError(f"Operation {op_id} not found in service {svc.name}")
        tpl = op._templates.get(template_id)
        if tpl is None:
            raise KeyError(f"Template {template_id} not found in operation {op.name}")
        return svc, op, tpl

    def get_service(self, service_id: int) -> ServiceDef:
        return self.services[service_id]

    def get_operation(self, service_id: int, op_id: int) -> OperationDef:
        return self.services[service_id]._operations[op_id]

    def get_template(self, service_id: int, op_id: int, template_id: int) -> TemplateDef:
        return self.services[service_id]._operations[op_id]._templates[template_id]

    def canonical_definition(self) -> bytes:
        """Return the stable bytes used to identify this codebook contract.

        The fingerprint deliberately includes every field that changes how a
        codon is interpreted, including the seed hash and parameter types.
        It excludes ``content_hash`` itself so it is never self-referential.
        """
        return json.dumps(
            self.to_dict(include_content_hash=False),
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
        ).encode('utf-8')

    @property
    def content_hash(self) -> bytes:
        """SHA-256 fingerprint of the canonical codebook contract."""
        return hashlib.sha256(self.canonical_definition()).digest()

    def verify_content_hash(self) -> bool:
        """Validate a declared fingerprint, if the definition includes one."""
        return not self.version.content_hash or self.version.content_hash == self.content_hash

    # -- serialization --

    def to_dict(self, include_content_hash: bool = True) -> dict:
        result = {
            'codebook_id': self.version.codebook_id,
            'version': self.version.version,
            'seed_hash': self.version.seed_hash.hex(),
            'capabilities': self.version.capabilities,
            'services': [
                {
                    'id': svc.id,
                    'name': svc.name,
                    'operations': [
                        {
                            'id': op.id,
                            'name': op.name,
                            'templates': [
                                {
                                    'id': t.id,
                                    'description': t.description,
                                    'params': t.params,
                                    'types': t.types,
                                    'defaults': t.defaults,
                                }
                                for t in sorted(op.templates, key=lambda template: template.id)
                            ]
                        }
                        for op in sorted(svc.operations, key=lambda op: op.id)
                    ]
                }
                for svc in sorted(self.services.values(), key=lambda svc: svc.id)
            ]
        }
        if include_content_hash and self.version.content_hash:
            result['content_hash'] = self.version.content_hash.hex()
        return result

    @classmethod
    def from_dict(cls, d: dict) -> 'Codebook':
        version = CodebookVersion(
            codebook_id=d['codebook_id'],
            version=d['version'],
            seed_hash=bytes.fromhex(d['seed_hash']),
            capabilities=d.get('capabilities', 0),
            content_hash=bytes.fromhex(d['content_hash']) if d.get('content_hash') else b'',
        )
        services = []
        for sd in d['services']:
            svc = ServiceDef(
                id=sd['id'],
                name=sd['name'],
                operations=[
                    OperationDef(
                        id=od['id'],
                        name=od['name'],
                        templates=[
                            TemplateDef(
                                id=td['id'],
                                description=td['description'],
                                params=td.get('params', []),
                                types=td.get('types', []),
                                defaults=td.get('defaults', {}),
                            )
                            for td in od['templates']
                        ]
                    )
                    for od in sd['operations']
                ]
            )
            services.append(svc)
        codebook = cls(version, services)
        if not codebook.verify_content_hash():
            raise ValueError("codebook content_hash does not match its definition")
        return codebook

    @classmethod
    def from_yaml_file(cls, path: str) -> 'Codebook':
        """Load a codebook definition from a YAML file."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        # Compute seed hash if a seed is provided
        if 'codebook_seed' in data:
            seed = bytes.fromhex(data.pop('codebook_seed'))
            data['seed_hash'] = hashlib.sha256(seed).hexdigest()
        elif 'seed_hash' not in data:
            raise ValueError("YAML must contain 'codebook_seed' or 'seed_hash'")
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Codebook generation from seed
# ---------------------------------------------------------------------------

def derive_master_seed(codebook_seed: bytes, session_nonce: bytes) -> bytes:
    """Derive the master seed for a session."""
    return hkdf(
        salt=codebook_seed,
        ikm=session_nonce,
        info=b"ANA-v1-codebook",
        length=64,
    )


def derive_subchain_seed(master_seed: bytes, chain_index: int) -> bytes:
    """Derive the sub-chain seed for rotation index."""
    return hkdf(
        salt=master_seed,
        ikm=chain_index.to_bytes(4, 'big'),
        info=b"ANA-v1-subchain",
        length=32,
    )


def derive_scramble(seed: bytes, service_id: int, op_id: int, template_id: int) -> tuple[int, int, int]:
    """
    Derive a scrambled (S,O,T) from a seed for a given sub-chain.

    When wired into the encode/decode path, this would make sub-chain
    rotation change codon byte values — the same logical operation maps
    to different raw bytes under different sub-chain seeds, providing
    "mapping forward secrecy".

    NOTE (v0.2.0): This function is defined but NOT yet wired into the
    CodonEncoder/CodonDecoder pipeline. Currently, sub-chain rotation
    only rotates HMAC keys, not codon mappings. Wiring this requires
    the codebook to track the current sub-chain index per session.
    """
    rng = ChaCha20RNG(seed + bytes([service_id, op_id, template_id]))
    s = rng.randint(1, 254)
    o = rng.randint(1, 254)
    t = rng.randint(0, 254)
    return (s, o, t)


def derive_hmac_key(master_seed: bytes, chain_index: int) -> bytes:
    """Derive an HMAC-SHA256 key from the master seed and chain index.

    Each sub-chain gets its own HMAC key for defense-in-depth:
    even if one sub-chain's HMAC key is compromised, others remain safe.
    """
    return hkdf(
        salt=master_seed,
        ikm=chain_index.to_bytes(4, 'big'),
        info=b"ANA-v1-hmac",
        length=32,
    )
