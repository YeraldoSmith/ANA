"""Tests for ANA-S security layer."""

import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana.security import (
    ANAIdentity, ANASecureSession, AEADCipher,
    HelloPacket, HelloAckPacket,
    derive_session_keys, _hkdf,
)


class TestANAIdentity:
    def test_generate(self):
        aid = ANAIdentity.generate()
        assert len(aid.aid_id) == 32
        assert aid.public_bytes()['aid_id'] == aid.aid_id.hex()

    def test_deterministic(self):
        a1 = ANAIdentity.generate()
        a2 = ANAIdentity.generate()
        assert a1.aid_id != a2.aid_id
        assert (a1.ed25519_pk.public_bytes_raw()
                != a2.ed25519_pk.public_bytes_raw())


class TestAEADCipher:
    def test_encrypt_decrypt(self):
        key = os.urandom(32)
        cipher = AEADCipher(key)
        nonce = b'\x00' * 12
        pt = b"test message for AEAD"
        ct = cipher.encrypt(pt, nonce)
        assert ct != pt
        assert len(ct) == len(pt) + 16  # +16 byte Poly1305 tag
        decrypted = cipher.decrypt(ct, nonce)
        assert decrypted == pt

    def test_tamper_detection(self):
        key = os.urandom(32)
        cipher = AEADCipher(key)
        nonce = b'\x00' * 12
        ct = bytearray(cipher.encrypt(b"test", nonce))
        ct[0] ^= 0xFF
        assert cipher.decrypt(bytes(ct), nonce) is None

    def test_wrong_key(self):
        c1 = AEADCipher(os.urandom(32))
        c2 = AEADCipher(os.urandom(32))
        nonce = b'\x00' * 12
        ct = c1.encrypt(b"test", nonce)
        assert c2.decrypt(ct, nonce) is None

    def test_wrong_nonce(self):
        cipher = AEADCipher(os.urandom(32))
        ct = cipher.encrypt(b"test", b'\x00' * 12)
        assert cipher.decrypt(ct, b'\x01' * 12) is None


class TestHandshake:
    def test_full_handshake(self):
        # Alice (initiator / Agent)
        alice = ANAIdentity.generate()
        # Bob (responder / API)
        bob = ANAIdentity.generate()

        # Alice creates HELLO
        alice_session = ANASecureSession(
            our_identity=alice,
            their_public_key=bob.aid_id,
        )
        hello = alice_session.create_hello()
        assert len(hello.serialize()) == 144

        # Bob handles HELLO, returns HELLO_ACK
        bob_session = ANASecureSession(our_identity=bob)
        hello_ack = bob_session.handle_hello(hello)
        assert len(hello_ack.serialize()) == 144

        # Alice completes handshake
        confirm = alice_session.complete_handshake(hello_ack)
        assert len(confirm) == 16

        # Bob verifies CONFIRM
        assert bob_session.verify_confirm(confirm) is True

        # Both sides have established sessions
        assert alice_session.is_established
        assert bob_session.is_established

    def test_encrypt_after_handshake(self):
        alice = ANAIdentity.generate()
        bob = ANAIdentity.generate()

        alice_session = ANASecureSession(
            our_identity=alice,
            their_public_key=bob.aid_id,
        )
        hello = alice_session.create_hello()

        bob_session = ANASecureSession(our_identity=bob)
        hello_ack = bob_session.handle_hello(hello)

        confirm = alice_session.complete_handshake(hello_ack)
        assert bob_session.verify_confirm(confirm)

        # Alice sends encrypted message to Bob
        msg = b"get_weather(city=Beijing)"
        ct = alice_session.encrypt(msg)
        pt = bob_session.decrypt(ct)
        assert pt == msg

        # Bob sends encrypted response to Alice
        resp = b"{temp: 28C, humidity: 65%}"
        ct2 = bob_session.encrypt(resp)
        pt2 = alice_session.decrypt(ct2)
        assert pt2 == resp

    def test_wrong_confirm_rejected(self):
        alice = ANAIdentity.generate()
        bob = ANAIdentity.generate()

        alice_session = ANASecureSession(
            our_identity=alice,
            their_public_key=bob.aid_id,
        )
        hello = alice_session.create_hello()

        bob_session = ANASecureSession(our_identity=bob)
        bob_session.handle_hello(hello)
        # Wrong confirm
        assert bob_session.verify_confirm(b'\x00' * 16) is False

    def test_signature_verification(self):
        alice = ANAIdentity.generate()
        bob = ANAIdentity.generate()

        alice_session = ANASecureSession(
            our_identity=alice,
            their_public_key=bob.aid_id,
        )
        hello = alice_session.create_hello()

        # Tamper with the signature
        tampered = HelloPacket(
            aid_id=hello.aid_id,
            eph_pk=hello.eph_pk,
            nonce=hello.nonce,
            signature=b'\x00' * 64,
        )
        bob_session = ANASecureSession(our_identity=bob)
        with pytest.raises(Exception):
            bob_session.handle_hello(tampered)


class TestHKDF:
    def test_derive_session_keys(self):
        shared = os.urandom(32)
        na = os.urandom(16)
        nb = os.urandom(16)
        keys = derive_session_keys(shared, na, nb)
        assert len(keys['session_seed']) == 64
        assert len(keys['aead_key_send']) == 32
        assert len(keys['aead_key_recv']) == 32

    def test_deterministic(self):
        shared = os.urandom(32)
        na = os.urandom(16)
        nb = os.urandom(16)
        k1 = derive_session_keys(shared, na, nb)
        k2 = derive_session_keys(shared, na, nb)
        assert k1['session_seed'] == k2['session_seed']
        assert k1['aead_key_send'] == k2['aead_key_send']


class TestHelloPacket:
    def test_roundtrip(self):
        pkt = HelloPacket(
            aid_id=os.urandom(32),
            eph_pk=os.urandom(32),
            nonce=os.urandom(16),
            signature=os.urandom(64),
        )
        assert HelloPacket.deserialize(pkt.serialize()) == pkt

    def test_bad_length(self):
        with pytest.raises(ValueError):
            HelloPacket.deserialize(b'\x00' * 100)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
