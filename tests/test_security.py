"""Tests for HMAC integrity and Bloom filter DoS protection."""

import os
import sys
import hashlib
import struct
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana.codebook import (
    Codebook, CodebookVersion, ServiceDef, OperationDef, TemplateDef,
    derive_master_seed, derive_subchain_seed, derive_hmac_key, hkdf,
)
from ana.packet import (
    Packet, PacketType, serialize_packet, deserialize_packet,
    make_codon, compute_hmac, verify_hmac,
    CAP_HMAC, HMAC_TAG_SIZE, HEADER_SIZE, CHECKSUM_SIZE,
)
from ana.session import Session

from ana.reliability import BloomFilter, ACKTracker, Heartbeat


class TestHMAC:
    def test_compute_and_verify(self):
        key = os.urandom(32)
        data = b"test message for HMAC"
        tag = compute_hmac(key, data)
        assert len(tag) == HMAC_TAG_SIZE
        assert verify_hmac(key, data, tag) is True

    def test_tamper_detection(self):
        key = os.urandom(32)
        data = b"test message"
        tag = compute_hmac(key, data)
        # Flip a bit
        tampered = data + b"\x00"
        assert verify_hmac(key, tampered, tag) is False

    def test_wrong_key(self):
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        data = b"test"
        tag = compute_hmac(key1, data)
        assert verify_hmac(key2, data, tag) is False

    def test_deterministic(self):
        key = os.urandom(32)
        data = b"deterministic test"
        assert compute_hmac(key, data) == compute_hmac(key, data)


class TestHMACDerivation:
    def test_derive_hmac_key(self):
        ms = os.urandom(64)
        k0 = derive_hmac_key(ms, 0)
        k1 = derive_hmac_key(ms, 1)
        assert len(k0) == 32
        assert k0 != k1

    def test_hmac_key_deterministic(self):
        ms = os.urandom(64)
        assert derive_hmac_key(ms, 42) == derive_hmac_key(ms, 42)


class TestHMACPacketRoundtrip:
    def test_serialize_with_hmac(self):
        key = os.urandom(32)
        p = make_codon(b'\x01\x02\x03\x04\x05\x06')
        wire = serialize_packet(p, pad=False, hmac_key=key)
        recovered = deserialize_packet(wire, hmac_key=key)
        assert recovered is not None
        assert recovered.payload == p.payload

    def test_serialize_hmac_tamper(self):
        key = os.urandom(32)
        p = make_codon(b'\x01\x02\x03')
        wire = bytearray(serialize_packet(p, pad=False, hmac_key=key))
        # Tamper with payload
        wire[HEADER_SIZE + 1] ^= 0xFF
        recovered = deserialize_packet(bytes(wire), hmac_key=key)
        assert recovered is None  # HMAC verification should fail

    def test_serialize_hmac_wrong_key(self):
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        p = make_codon(b'\x01\x02\x03')
        wire = serialize_packet(p, pad=False, hmac_key=key1)
        recovered = deserialize_packet(wire, hmac_key=key2)
        assert recovered is None

    def test_no_hmac_backward_compat(self):
        """Without HMAC key, serialization still works (CRC only)."""
        p = make_codon(b'\x01\x02\x03')
        wire = serialize_packet(p, pad=False, hmac_key=None)
        recovered = deserialize_packet(wire, hmac_key=None)
        assert recovered is not None
        assert recovered.payload == p.payload

    def test_packet_size_with_hmac(self):
        key = os.urandom(32)
        p = make_codon(b'\x01\x02\x03')
        wire_no_hmac = serialize_packet(p, pad=False, hmac_key=None)
        wire_hmac = serialize_packet(p, pad=False, hmac_key=key)
        assert len(wire_hmac) == len(wire_no_hmac) + HMAC_TAG_SIZE


class TestBloomFilter:
    def test_add_and_check(self):
        bf = BloomFilter(size_bits=1024)
        bf.add(b'\x01\x02\x03')
        assert bf.might_contain(b'\x01\x02\x03') is True

    def test_definitely_not(self):
        bf = BloomFilter(size_bits=1024)
        bf.add(b'\x01\x02\x03')
        assert bf.might_contain(b'\xFF\xFF\xFF') is False

    def test_false_positive_rate(self):
        """With 1000 entries and 8192 bits, FPR should be < 3%."""
        bf = BloomFilter(size_bits=8192, hash_count=7)
        for i in range(1000):
            bf.add(struct.pack('>I', i)[:3])
        # Test 1000 unknowns
        fps = 0
        for i in range(1000, 2000):
            if bf.might_contain(struct.pack('>I', i)[:3]):
                fps += 1
        fpr = fps / 1000
        assert fpr < 0.03, f"FPR {fpr:.3f} exceeds 3%"

    def test_from_codebook(self):
        cb = Codebook(
            version=CodebookVersion(
                codebook_id="test-v1", version=1,
                seed_hash=hashlib.sha256(b"test").digest(),
            ),
            services=[
                ServiceDef(id=1, name="weather", operations=[
                    OperationDef(id=1, name="get_forecast", templates=[
                        TemplateDef(id=0, description="by city", params=["city"], types=["string"]),
                    ]),
                ]),
            ]
        )
        bf = BloomFilter.from_codebook(cb)
        assert bf.might_contain(b'\x01\x01\x00') is True
        assert bf.might_contain(b'\x63\x01\x00') is False

    def test_reject_noise(self):
        """Noise codon [0x00,0x00,0x00] is NOT added to bloom filter."""
        bf = BloomFilter(size_bits=1024)
        # Noise codon should not be in the filter unless explicitly added
        assert bf.might_contain(b'\x00\x00\x00') is False


class TestSessionHMAC:
    def test_hmac_enabled_with_capability(self):
        cb = Codebook(
            version=CodebookVersion(
                codebook_id="test-v1", version=1,
                seed_hash=hashlib.sha256(b"test").digest(),
                capabilities=CAP_HMAC,  # HMAC capability set
            ),
            services=[],
        )
        s = Session(side="agent")
        s.establish(cb, cb.version, os.urandom(32))
        assert s.hmac_enabled is True
        assert s.hmac_key is not None
        assert len(s.hmac_key) == 32

    def test_hmac_disabled_without_capability(self):
        cb = Codebook(
            version=CodebookVersion(
                codebook_id="test-v1", version=1,
                seed_hash=hashlib.sha256(b"test").digest(),
                capabilities=0,  # No HMAC
            ),
            services=[],
        )
        s = Session(side="agent")
        s.establish(cb, cb.version, os.urandom(32))
        assert s.hmac_enabled is False
        assert s.hmac_key is None

    def test_hmac_key_rotates(self):
        cb = Codebook(
            version=CodebookVersion(
                codebook_id="test-v1", version=1,
                seed_hash=hashlib.sha256(b"test").digest(),
                capabilities=CAP_HMAC,
            ),
            services=[],
        )
        s = Session(side="agent")
        s.establish(cb, cb.version, os.urandom(32))
        k0 = s.hmac_key
        s.rotate(1)
        k1 = s.hmac_key
        assert k0 != k1


class TestACKTracker:
    def test_track_and_ack(self):
        tracker = ACKTracker(retransmit_timeout=1.0)
        tracker.track(5, b"test data")
        assert tracker.pending_count == 1
        assert tracker.ack(5) is True
        assert tracker.pending_count == 0

    def test_ack_unknown_seq(self):
        tracker = ACKTracker()
        assert tracker.ack(999) is False

    def test_retransmit(self):
        tracker = ACKTracker(retransmit_timeout=0.001, max_retransmits=2)
        tracker.track(1, b"pkt1")
        import time
        time.sleep(0.002)
        sent = []
        timeouts = tracker.check(lambda d: sent.append(d))
        assert len(sent) == 1
        assert sent[0] == b"pkt1"
        assert len(timeouts) == 0  # First retry, not exhausted yet


class TestHeartbeat:
    def test_should_ping_initially(self):
        hb = Heartbeat(interval=0.001)
        import time
        time.sleep(0.002)
        assert hb.should_ping() is True

    def test_should_not_ping_after_send(self):
        hb = Heartbeat(interval=30.0)
        hb.sent()
        assert hb.should_ping() is False

    def test_dead_detection(self):
        hb = Heartbeat(timeout=0.001)
        import time
        time.sleep(0.002)
        assert hb.is_dead() is True

    def test_alive_after_receive(self):
        hb = Heartbeat(timeout=0.001)
        hb.received()
        assert hb.is_dead() is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
