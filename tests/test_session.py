"""Tests for session state machine."""

import os
import sys
import hashlib
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana.codebook import (
    Codebook, CodebookVersion, ServiceDef, OperationDef, TemplateDef,
)
from ana.session import Session, SessionState, SessionConfig


@pytest.fixture
def test_codebook():
    return Codebook(
        version=CodebookVersion(
            codebook_id="test-v1", version=1,
            seed_hash=hashlib.sha256(b"test_seed").digest(),
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


class TestSessionLifecycle:
    def test_initial_state(self):
        s = Session(side="agent")
        assert s.state == SessionState.DISCONNECTED
        assert s.codebook is None

    def test_full_lifecycle(self, test_codebook):
        s = Session(side="agent")
        assert s.state == SessionState.DISCONNECTED

        s.start_negotiation()
        assert s.state == SessionState.NEGOTIATING

        s.establish(test_codebook, test_codebook.version, os.urandom(32))
        assert s.state == SessionState.ACTIVE
        assert s.encoder is not None
        assert s.decoder is not None
        assert s.master_seed is not None

        s.rotate(3)
        assert s.current_chain_index == 3
        assert s.state == SessionState.ACTIVE
        assert s.current_chain_packets == 0

        s.fallback()
        assert s.state == SessionState.FALLBACK

        s.recover_from_fallback(test_codebook, test_codebook.version, os.urandom(32))
        assert s.state == SessionState.ACTIVE

        s.close()
        assert s.state == SessionState.CLOSED

    def test_cannot_negotiate_from_active(self, test_codebook):
        s = Session(side="agent")
        s.start_negotiation()
        s.establish(test_codebook, test_codebook.version, os.urandom(32))
        with pytest.raises(RuntimeError):
            s.start_negotiation()

    def test_cannot_rotate_from_disconnected(self):
        s = Session(side="agent")
        with pytest.raises(RuntimeError):
            s.rotate(1)

    def test_invalid_side(self):
        with pytest.raises(ValueError):
            Session(side="invalid")


class TestSequenceTracking:
    def test_next_send_seq(self):
        s = Session(side="agent")
        assert s.next_send_seq(0) == 0
        assert s.next_send_seq(0) == 1
        assert s.next_send_seq(0) == 2

    def test_different_streams(self):
        s = Session(side="agent")
        seq_a = s.next_send_seq(0)
        seq_b = s.next_send_seq(1)
        assert seq_a == 0
        assert seq_b == 0  # independent per stream

    def test_recv_seq_valid(self):
        s = Session(side="api")
        assert s.check_recv_seq(0, 0) is True
        assert s.check_recv_seq(0, 5) is True
        assert s.check_recv_seq(0, 3) is True  # within reorder window

    def test_recv_seq_replay(self):
        s = Session(side="api")
        assert s.check_recv_seq(0, 100) is True
        # Replay of old sequence outside window
        assert s.check_recv_seq(0, 0) is False  # 100 - 100 = 0 at window boundary
        # Actually 100 - 100 = 0, and 0 < 0 is False, so 0 <= 0 is True...
        # Let me check: seq=0, last=100, window=100
        # seq > last? 0 > 100 = False. seq > last - window? 0 > 0 = False.
        # So should return False. Let me test more carefully:
        assert s.check_recv_seq(0, -10) is False


class TestRotation:
    def test_needs_rotation(self, test_codebook):
        s = Session(side="agent")
        s.establish(test_codebook, test_codebook.version, os.urandom(32))

        for _ in range(999):
            s.record_send()
        assert s.needs_rotation() is False

        s.record_send()
        assert s.needs_rotation() is True

    def test_rotation_resets_counter(self, test_codebook):
        s = Session(side="agent")
        s.establish(test_codebook, test_codebook.version, os.urandom(32))

        for _ in range(1000):
            s.record_send()
        assert s.needs_rotation() is True

        s.rotate(1)
        assert s.current_chain_packets == 0
        assert s.needs_rotation() is False


class TestSessionExpiry:
    def test_not_expired_when_active(self, test_codebook):
        s = Session(side="agent")
        s.establish(test_codebook, test_codebook.version, os.urandom(32))
        assert s.is_expired is False

    def test_expired(self, test_codebook):
        s = Session(side="agent")
        s.config.session_timeout = 0  # immediate expiry
        s.establish(test_codebook, test_codebook.version, os.urandom(32))
        time.sleep(0.01)
        assert s.is_expired is True

    def test_closed_is_expired(self):
        s = Session(side="agent")
        s.close()
        assert s.is_expired is True


class TestSubchainSeeds:
    def test_different_chains_different_seeds(self, test_codebook):
        s = Session(side="agent")
        s.establish(test_codebook, test_codebook.version, os.urandom(32))
        seed0 = s.get_subchain_seed(0)
        seed1 = s.get_subchain_seed(1)
        assert seed0 != seed1

    def test_same_chain_same_seed(self, test_codebook):
        s = Session(side="agent")
        s.establish(test_codebook, test_codebook.version, os.urandom(32))
        assert s.get_subchain_seed(2) == s.get_subchain_seed(2)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
