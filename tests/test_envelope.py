"""Tests for the v0.3 strict call envelope and codebook fingerprinting."""

import copy
import hashlib

import pytest

from ana.codebook import Codebook, CodebookVersion, OperationDef, ServiceDef, TemplateDef
from ana.codon import CodonDecoder, CodonEncoder
from ana.envelope import CallEnvelope, FIRE_AND_FORGET, HEADER_SIZE


def make_codebook(description="forecast by city"):
    return Codebook(
        CodebookVersion("weather-v1", 1, hashlib.sha256(b"seed").digest()),
        [ServiceDef(1, "weather", [OperationDef(1, "forecast", [TemplateDef(
            0, description, ["city", "days"], ["string", "uint8"], {"days": 7},
        )])])],
    )


class TestCodebookFingerprint:
    def test_canonical_fingerprint_is_stable(self):
        assert make_codebook().content_hash == make_codebook().content_hash

    def test_canonical_fingerprint_ignores_definition_order(self):
        first = make_codebook().to_dict()
        first["services"].append({"id": 2, "name": "alerts", "operations": []})
        reordered = copy.deepcopy(first)
        reordered["services"] = list(reversed(reordered["services"]))
        assert Codebook.from_dict(first).content_hash == Codebook.from_dict(reordered).content_hash

    def test_fingerprint_changes_with_contract(self):
        assert make_codebook().content_hash != make_codebook("forecast in metric units").content_hash

    def test_rejects_mismatched_declared_fingerprint(self):
        codebook = make_codebook()
        definition = codebook.to_dict()
        definition["content_hash"] = (b"x" * 32).hex()
        with pytest.raises(ValueError, match="content_hash"):
            Codebook.from_dict(definition)


class TestCallEnvelope:
    def test_roundtrip_and_decode(self):
        codebook = make_codebook()
        request_id = bytes(range(16))
        envelope = CodonEncoder(codebook).encode_envelope(
            1, 1, 0, ["Beijing", 7], deadline_ms=2500,
            request_id=request_id, flags=FIRE_AND_FORGET,
        )
        decoded, received = CodonDecoder(codebook).decode_envelope(envelope.serialize())
        assert decoded["params"] == {"city": "Beijing", "days": 7}
        assert received.request_id == request_id
        assert received.deadline_ms == 2500
        assert received.flags == FIRE_AND_FORGET

    def test_rejects_different_codebook(self):
        envelope = CodonEncoder(make_codebook()).encode_envelope(1, 1, 0, ["Beijing", 7])
        with pytest.raises(ValueError, match="fingerprint mismatch"):
            CodonDecoder(make_codebook("different contract")).decode_envelope(envelope.serialize())

    def test_rejects_trailing_bytes(self):
        envelope = CallEnvelope.for_codebook(make_codebook(), b"\x01\x01\x00")
        with pytest.raises(ValueError, match="length"):
            CallEnvelope.deserialize(envelope.serialize() + b"\x00")

    def test_rejects_malformed_header(self):
        with pytest.raises(ValueError, match="truncated"):
            CallEnvelope.deserialize(b"ANA3")
        with pytest.raises(ValueError, match="magic"):
            CallEnvelope.deserialize(b"BAD!" + b"\x01" * (HEADER_SIZE - 4))

    def test_rejects_reserved_flags(self):
        with pytest.raises(ValueError, match="reserved flags"):
            CallEnvelope.for_codebook(make_codebook(), b"\x01\x01\x00", flags=0x80)
