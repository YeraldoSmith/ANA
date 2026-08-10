"""Tests for codon encoding/decoding."""

import os
import sys
import hashlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana.codebook import (
    Codebook, CodebookVersion, ServiceDef, OperationDef, TemplateDef,
)
from ana.codon import (
    CodonEncoder, CodonDecoder,
    encode_varint, decode_varint,
    encode_signed_varint, decode_signed_varint,
    encode_params, decode_params,
    NOOP_SERVICE, NOOP_OPERATION, NOOP_TEMPLATE,
)


class TestVarint:
    def test_small(self):
        assert encode_varint(0) == b'\x00'
        assert encode_varint(1) == b'\x01'
        assert encode_varint(127) == b'\x7f'

    def test_two_byte(self):
        assert encode_varint(128) == b'\x80\x01'
        assert encode_varint(300) == b'\xac\x02'

    def test_roundtrip(self):
        for val in [0, 1, 127, 128, 255, 256, 1000, 65535, 1000000]:
            encoded = encode_varint(val)
            decoded, offset = decode_varint(encoded)
            assert decoded == val
            assert offset == len(encoded)

    def test_signed(self):
        for val in [0, 1, -1, 127, -127, 1000, -1000]:
            encoded = encode_signed_varint(val)
            decoded, offset = decode_signed_varint(encoded)
            assert decoded == val


class TestParamEncoding:
    def test_string_params(self):
        encoded = encode_params(["Beijing", 7], ["string", "uint8"])
        assert b"Beijing" in encoded
        values, _ = decode_params(encoded, ["string", "uint8"])
        assert values == ["Beijing", 7]

    def test_numeric_params(self):
        encoded = encode_params([35.5, -120, 3], ["float32", "int32", "uint8"])
        values, _ = decode_params(encoded, ["float32", "int32", "uint8"])
        assert values[0] == pytest.approx(35.5, abs=0.1)
        assert values[1] == -120
        assert values[2] == 3

    def test_bool_params(self):
        encoded = encode_params([True, False], ["bool", "bool"])
        values, _ = decode_params(encoded, ["bool", "bool"])
        assert values == [True, False]

    def test_bytes_params_do_not_leave_a_separator(self):
        encoded = encode_params([b'\x00\xff', 7], ["bytes", "uint8"])
        values, offset = decode_params(encoded, ["bytes", "uint8"])
        assert values == [b'\x00\xff', 7]
        assert offset == len(encoded)

    def test_type_count_mismatch(self):
        with pytest.raises(ValueError):
            encode_params(["a", "b"], ["string"])


class TestCodon:
    def make_codebook(self):
        return Codebook(
            version=CodebookVersion(
                codebook_id="test-v1", version=1,
                seed_hash=hashlib.sha256(b"test").digest(),
            ),
            services=[
                ServiceDef(id=1, name="weather", operations=[
                    OperationDef(id=1, name="get_forecast", templates=[
                        TemplateDef(id=0, description="by city",
                                    params=["city", "days"],
                                    types=["string", "uint8"]),
                    ]),
                ]),
            ]
        )

    def test_encode_decode_roundtrip(self):
        cb = self.make_codebook()
        encoder = CodonEncoder(cb)
        decoder = CodonDecoder(cb)

        codon = encoder.encode(1, 1, 0, ["Beijing", 7])
        decoded, offset = decoder.decode(codon)

        assert decoded['service_name'] == "weather"
        assert decoded['operation_name'] == "get_forecast"
        assert decoded['params'] == {"city": "Beijing", "days": 7}
        assert decoded['is_response'] is False
        assert decoded['is_noise'] is False

    def test_noise_codon(self):
        cb = self.make_codebook()
        decoder = CodonDecoder(cb)

        noise = bytes([NOOP_SERVICE, NOOP_OPERATION, NOOP_TEMPLATE])
        decoded, _ = decoder.decode(noise)
        assert decoded['is_noise'] is True

    def test_is_noise_static(self):
        noise = bytes([NOOP_SERVICE, NOOP_OPERATION, NOOP_TEMPLATE])
        assert CodonDecoder.is_noise(noise)
        assert not CodonDecoder.is_noise(b'\x01\x02\x03')

    def test_response_flag(self):
        cb = self.make_codebook()
        encoder = CodonEncoder(cb)
        decoder = CodonDecoder(cb)

        codon = encoder.encode(1, 1, 0, ["OK", 7], is_response=True)
        decoded, _ = decoder.decode(codon)
        assert decoded['is_response'] is True

    def test_encode_multi(self):
        cb = self.make_codebook()
        encoder = CodonEncoder(cb)
        decoder = CodonDecoder(cb)

        codon_bytes = encoder.encode_multi([
            (1, 1, 0, ["Beijing", 7], False),
            (1, 1, 0, ["Tokyo", 3], False),
        ])
        results = decoder.decode_multi(codon_bytes)
        assert len(results) == 2
        assert results[0]['params']['city'] == "Beijing"
        assert results[1]['params']['city'] == "Tokyo"

    def test_make_noise(self):
        cb = self.make_codebook()
        encoder = CodonEncoder(cb)
        noise = encoder.make_noise(3)
        assert len(noise) == 9  # 3 * 3 bytes per noise codon
        assert noise == b'\x00\x00\x00' * 3

    def test_codon_size(self):
        size = CodonEncoder.codon_size(1, 1, 0, ["Tokyo", 3], ["string", "uint8"])
        encoded = CodonEncoder(
            self.make_codebook()
        ).encode(1, 1, 0, ["Tokyo", 3])
        assert size == len(encoded)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
