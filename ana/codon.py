"""
Codon encoding and decoding.

A codon is a compact binary representation of an API operation call.
Format: [service_id: u8][operation_id: u8][template_id: u8][param_values: varint...]

Special codons:
  - [0x00, 0x00, 0x00] = NOOP / noise (discarded)
  - [0xFF, 0xFF, 0xFF] = Reserved / extension marker
"""

import struct
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Unsigned LEB128 varint encoding
# ---------------------------------------------------------------------------


def encode_varint(value: int) -> bytes:
    """Encode an unsigned integer as LEB128 varint bytes."""
    if value < 0:
        raise ValueError(f"varint requires non-negative value, got {value}")
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value & 0x7F)
    return bytes(result) if result else b'\x00'


def decode_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """
    Decode an unsigned LEB128 varint from bytes.
    Returns (value, new_offset).
    """
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        value |= (byte & 0x7F) << shift
        offset += 1
        if not (byte & 0x80):
            return value, offset
        shift += 7
        if shift > 63:
            raise OverflowError("varint too large")
    raise ValueError("truncated varint")


def encode_signed_varint(value: int) -> bytes:
    """Encode a signed integer as zigzag + unsigned varint."""
    if value >= 0:
        zigzag = value * 2
    else:
        zigzag = (-value) * 2 - 1
    return encode_varint(zigzag)


def decode_signed_varint(data: bytes, offset: int = 0) -> tuple[int, int]:
    """Decode a zigzag varint back to signed integer."""
    zigzag, new_offset = decode_varint(data, offset)
    if zigzag % 2 == 0:
        return zigzag // 2, new_offset
    else:
        return -(zigzag // 2) - 1, new_offset


# ---------------------------------------------------------------------------
# Parameter encoding
# ---------------------------------------------------------------------------

_PARAM_ENCODERS = {
    'string': lambda v: v.encode('utf-8'),
    'uint8': lambda v: struct.pack('B', v),
    'uint16': lambda v: struct.pack('>H', v),
    'uint32': lambda v: struct.pack('>I', v),
    'int32': lambda v: struct.pack('>i', v),
    'float32': lambda v: struct.pack('>f', v),
    'bool': lambda v: b'\x01' if v else b'\x00',
    'bytes': lambda v: struct.pack('>H', len(v)) + (v if isinstance(v, bytes) else bytes(v)),
}

_PARAM_DECODERS = {
    'string': lambda b, off: (b[off:].split(b'\x00', 1)[0].decode('utf-8'), off + len(b[off:].split(b'\x00', 1)[0]) + 1),
    'uint8': lambda b, off: (struct.unpack('B', b[off:off+1])[0], off + 1),
    'uint16': lambda b, off: (struct.unpack('>H', b[off:off+2])[0], off + 2),
    'uint32': lambda b, off: (struct.unpack('>I', b[off:off+4])[0], off + 4),
    'int32': lambda b, off: (struct.unpack('>i', b[off:off+4])[0], off + 4),
    'float32': lambda b, off: (struct.unpack('>f', b[off:off+4])[0], off + 4),
    'bool': lambda b, off: (b[off] != 0, off + 1),
    # bytes is length-prefixed: [len: uint16][data]
    'bytes': lambda b, off: (b[off+2:off+2+struct.unpack('>H', b[off:off+2])[0]],
                              off + 2 + struct.unpack('>H', b[off:off+2])[0]),
}


def encode_params(params: list, types: list[str]) -> bytes:
    """Encode a list of parameter values according to their types.

    Variable-length types (string, bytes) are null-terminated.
    Fixed-length types are packed directly.
    """
    if len(params) != len(types):
        raise ValueError(f"param count {len(params)} != type count {len(types)}")
    result = bytearray()
    for val, typ in zip(params, types):
        encoder = _PARAM_ENCODERS.get(typ)
        if encoder is None:
            raise ValueError(f"Unknown param type: {typ}")
        encoded = encoder(val)
        result.extend(encoded)
        if typ in ('string', 'bytes'):
            result.append(0x00)  # null terminator
    return bytes(result)


def decode_params(data: bytes, types: list[str], offset: int = 0) -> tuple[list, int]:
    """Decode parameter values from binary data."""
    result = []
    for typ in types:
        decoder = _PARAM_DECODERS.get(typ)
        if decoder is None:
            raise ValueError(f"Unknown param type: {typ}")
        val, offset = decoder(data, offset)
        result.append(val)
    return result, offset


# ---------------------------------------------------------------------------
# Codon
# ---------------------------------------------------------------------------

# Reserved values
NOOP_SERVICE = 0x00
NOOP_OPERATION = 0x00
NOOP_TEMPLATE = 0x00
RESERVED_SERVICE = 0xFF
RESERVED_OPERATION = 0xFF
RESERVED_TEMPLATE = 0xFF

# Control operations (Service 0xFF)
CTRL_PING = 0x04      # [0xFF, 0x04, 0x00] — heartbeat ping
CTRL_PONG = 0x05      # [0xFF, 0x05, 0x00] — heartbeat pong
CTRL_TEARDOWN = 0x02  # [0xFF, 0x02, 0x00] — graceful session close

# Response marker: operation IDs with high bit set
RESPONSE_FLAG = 0x80


class CodonEncoder:
    """Encodes API operations into codon bytes."""

    def __init__(self, codebook):
        self.codebook = codebook

    def encode(self, service_id: int, op_id: int, template_id: int,
               params: Optional[list] = None, is_response: bool = False) -> bytes:
        """Encode a single operation call as a codon.

        Args:
            service_id: Service identifier.
            op_id: Operation identifier.
            template_id: Parameter template identifier.
            params: Runtime parameter values (fills template wildcards).
            is_response: If True, sets the response flag on the operation byte.

        Returns:
            Encoded codon bytes.
        """
        op_byte = op_id
        if is_response:
            op_byte |= RESPONSE_FLAG

        header = bytes([service_id, op_byte, template_id])

        if params:
            svc, op, tpl = self.codebook.resolve(service_id, op_id, template_id)
            param_bytes = encode_params(params, tpl.types)
        else:
            param_bytes = b''

        return header + param_bytes

    def encode_multi(self, calls: list[tuple]) -> bytes:
        """Encode multiple operations into a single codon payload.

        Args:
            calls: List of (service_id, op_id, template_id, params, is_response) tuples.

        Returns:
            Concatenated codon bytes.
        """
        return b''.join(
            self.encode(s, o, t, p, r)
            for (s, o, t, p, r) in calls
        )

    def make_noise(self, count: int = 1) -> bytes:
        """Generate noise codons (NOOPs)."""
        return bytes([NOOP_SERVICE, NOOP_OPERATION, NOOP_TEMPLATE]) * count

    @staticmethod
    def codon_size(service_id: int, op_id: int, template_id: int,
                   params: Optional[list] = None, types: Optional[list[str]] = None) -> int:
        """Calculate the encoded size of a codon without encoding it."""
        size = 3  # header
        if params and types:
            size += len(encode_params(params, types))
        return size


class CodonDecoder:
    """Decodes codon bytes back into API operation descriptors."""

    def __init__(self, codebook):
        self.codebook = codebook

    def decode(self, codon_bytes: bytes, offset: int = 0) -> tuple[dict, int]:
        """Decode a single codon.

        Returns (decoded_dict, new_offset).

        decoded_dict has keys: service_name, operation_name,
          template_description, params, is_response, is_noise, is_reserved
        """
        if offset + 3 > len(codon_bytes):
            raise ValueError(f"truncated codon at offset {offset}")

        service_id = codon_bytes[offset]
        op_byte = codon_bytes[offset + 1]
        template_id = codon_bytes[offset + 2]
        is_response = bool(op_byte & RESPONSE_FLAG)
        op_id = op_byte & ~RESPONSE_FLAG
        offset += 3

        # Special codons
        if service_id == NOOP_SERVICE and op_id == NOOP_OPERATION and template_id == NOOP_TEMPLATE:
            return {
                'is_noise': True,
                'is_response': False,
                'is_reserved': False,
                'service_name': 'noop',
                'operation_name': 'noop',
                'template_description': 'noise',
                'params': {},
            }, offset

        if (service_id == RESERVED_SERVICE and op_id == RESERVED_OPERATION
                and template_id == RESERVED_TEMPLATE):
            return {
                'is_noise': False,
                'is_response': False,
                'is_reserved': True,
                'is_control': False,
                'service_name': 'reserved',
                'operation_name': 'reserved',
                'template_description': 'extension',
                'params': {},
            }, offset

        # Control codons (Service 0xFF, specific operations)
        if service_id == RESERVED_SERVICE:
            if op_id == CTRL_PING:
                return {
                    'is_noise': False, 'is_response': False, 'is_reserved': False,
                    'is_control': True, 'control_type': 'ping',
                    'service_name': '_control', 'operation_name': 'ping',
                    'template_description': 'heartbeat ping', 'params': {},
                }, offset
            if op_id == CTRL_PONG:
                return {
                    'is_noise': False, 'is_response': False, 'is_reserved': False,
                    'is_control': True, 'control_type': 'pong',
                    'service_name': '_control', 'operation_name': 'pong',
                    'template_description': 'heartbeat pong', 'params': {},
                }, offset
            if op_id == CTRL_TEARDOWN:
                return {
                    'is_noise': False, 'is_response': False, 'is_reserved': False,
                    'is_control': True, 'control_type': 'teardown',
                    'service_name': '_control', 'operation_name': 'teardown',
                    'template_description': 'session close', 'params': {},
                }, offset

        # Resolve in codebook
        svc, op, tpl = self.codebook.resolve(service_id, op_id, template_id)

        # Decode parameters
        param_data = codon_bytes[offset:]
        params = {}
        if tpl.types:
            param_values, _ = decode_params(param_data, tpl.types)
            params = dict(zip(tpl.params, param_values))
            # advance past consumed parameter bytes
            consumed = len(encode_params(param_values, tpl.types))
            offset += consumed

        return {
            'is_noise': False,
            'is_response': is_response,
            'is_reserved': False,
            'service_name': svc.name,
            'operation_name': op.name,
            'template_description': tpl.description,
            'params': params,
            'service_id': service_id,
            'operation_id': op_id,
            'template_id': template_id,
        }, offset

    def decode_multi(self, codon_bytes: bytes) -> list[dict]:
        """Decode multiple codons from a byte string."""
        results = []
        offset = 0
        while offset < len(codon_bytes):
            try:
                decoded, offset = self.decode(codon_bytes, offset)
                results.append(decoded)
            except (ValueError, KeyError) as e:
                results.append({
                    'is_noise': False,
                    'is_response': False,
                    'is_reserved': False,
                    'error': str(e),
                    'raw_bytes': codon_bytes[offset:offset+3].hex(),
                })
                break
        return results

    @staticmethod
    def is_noise(codon_bytes: bytes, offset: int = 0) -> bool:
        """Check if bytes at offset represent a noise codon."""
        if offset + 3 > len(codon_bytes):
            return False
        return (codon_bytes[offset] == NOOP_SERVICE
                and codon_bytes[offset + 1] == NOOP_OPERATION
                and codon_bytes[offset + 2] == NOOP_TEMPLATE)
