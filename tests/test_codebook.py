"""Tests for codebook module."""

import os
import sys
import hashlib
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana.codebook import (
    Codebook, CodebookVersion, ServiceDef, OperationDef, TemplateDef,
    hkdf, derive_master_seed, derive_subchain_seed,
    ChaCha20RNG,
)


class TestCodebookVersion:
    def test_roundtrip(self):
        cv = CodebookVersion(
            codebook_id="test-v1",
            version=3,
            seed_hash=hashlib.sha256(b"test_seed").digest(),
            capabilities=15,
        )
        d = cv.to_dict()
        cv2 = CodebookVersion.from_dict(d)
        assert cv2.codebook_id == "test-v1"
        assert cv2.version == 3
        assert cv2.seed_hash == cv.seed_hash
        assert cv2.capabilities == 15


class TestCodebook:
    def make_test_codebook(self):
        return Codebook(
            version=CodebookVersion(
                codebook_id="test-v1",
                version=1,
                seed_hash=hashlib.sha256(b"test").digest(),
            ),
            services=[
                ServiceDef(id=1, name="weather", operations=[
                    OperationDef(id=1, name="get_forecast", templates=[
                        TemplateDef(id=0, description="by city",
                                    params=["city", "days"],
                                    types=["string", "uint8"],
                                    defaults={"days": 7}),
                    ]),
                ]),
            ]
        )

    def test_resolve(self):
        cb = self.make_test_codebook()
        svc, op, tpl = cb.resolve(1, 1, 0)
        assert svc.name == "weather"
        assert op.name == "get_forecast"
        assert tpl.description == "by city"
        assert tpl.params == ["city", "days"]

    def test_resolve_unknown_service(self):
        cb = self.make_test_codebook()
        with pytest.raises(KeyError, match="Service 99"):
            cb.resolve(99, 1, 0)

    def test_resolve_unknown_operation(self):
        cb = self.make_test_codebook()
        with pytest.raises(KeyError, match="Operation 99"):
            cb.resolve(1, 99, 0)

    def test_to_dict_and_back(self):
        cb = self.make_test_codebook()
        d = cb.to_dict()
        cb2 = Codebook.from_dict(d)
        svc, op, tpl = cb2.resolve(1, 1, 0)
        assert svc.name == "weather"
        assert op.name == "get_forecast"

    def test_from_yaml(self):
        yaml_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'examples', 'weather_service.yaml'
        )
        cb = Codebook.from_yaml_file(yaml_path)
        assert cb.version.codebook_id == "weather-v1"
        assert 1 in cb.services
        assert cb.services[1].name == "weather"


class TestHKDF:
    def test_rfc5869_test_vector_1(self):
        """RFC 5869 Test Case 1."""
        ikm = bytes.fromhex("0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b")
        salt = bytes.fromhex("000102030405060708090a0b0c")
        info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
        okm = hkdf(salt, ikm, info, 42)
        expected = bytes.fromhex(
            "3cb25f25faacd57a90434f64d0362f2a"
            "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
            "34007208d5b887185865"
        )
        assert okm == expected

    def test_derive_master_seed(self):
        seed = os.urandom(32)
        nonce = os.urandom(32)
        ms = derive_master_seed(seed, nonce)
        assert len(ms) == 64
        # Deterministic: same inputs → same output
        assert derive_master_seed(seed, nonce) == ms

    def test_derive_subchain_seed(self):
        ms = os.urandom(64)
        s0 = derive_subchain_seed(ms, 0)
        s1 = derive_subchain_seed(ms, 1)
        assert len(s0) == 32
        assert s0 != s1  # different chains have different seeds


class TestChaCha20RNG:
    def test_deterministic(self):
        rng1 = ChaCha20RNG(b"test_seed_32_bytes___________")
        rng2 = ChaCha20RNG(b"test_seed_32_bytes___________")
        assert rng1.randbytes(100) == rng2.randbytes(100)

    def test_different_seeds(self):
        rng1 = ChaCha20RNG(b"seed_a_______________________")
        rng2 = ChaCha20RNG(b"seed_b_______________________")
        assert rng1.randbytes(100) != rng2.randbytes(100)

    def test_randint_range(self):
        rng = ChaCha20RNG(os.urandom(32))
        for _ in range(100):
            val = rng.randint(0, 255)
            assert 0 <= val <= 255

    def test_randint_uniformity(self):
        rng = ChaCha20RNG(os.urandom(32))
        # Binomial test on 0/1 distribution
        ones = sum(rng.randint(0, 1) for _ in range(1000))
        assert 400 < ones < 600  # very generous bounds


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
