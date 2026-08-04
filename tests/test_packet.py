"""Tests for packet serialization."""

import os
import sys
import struct
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana.packet import (
    Packet, PacketType, PacketFlags,
    serialize_packet, deserialize_packet,
    make_negotiate, make_negotiate_ack, make_negotiate_confirm,
    make_codon, make_codon_ack, make_rotate, make_rotate_ack,
    make_error, make_fallback,
    crc16, HEADER_SIZE, PACKET_OVERHEAD, MAGIC,
    ErrorCode, ALLOWED_SIZES,
)


class TestCRC16:
    def test_known_value(self):
        assert crc16(b"123456789") == 0x29B1

    def test_empty(self):
        assert crc16(b"") == 0xFFFF


class TestPacketFlags:
    def test_pack_unpack(self):
        flags = PacketFlags.pack(PacketType.CODON, has_noise=True, is_fragmented=False, is_ack=True)
        ptype, noise, frag, ack = PacketFlags.unpack(flags)
        assert ptype == PacketType.CODON
        assert noise is True
        assert frag is False
        assert ack is True

    def test_all_types(self):
        for pt in PacketType:
            flags = PacketFlags.pack(pt)
            unpacked, _, _, _ = PacketFlags.unpack(flags)
            assert unpacked == pt

    def test_ack_flag(self):
        flags = PacketFlags.pack(PacketType.CODON, is_ack=True)
        _, _, _, ack = PacketFlags.unpack(flags)
        assert ack is True


class TestPacket:
    def test_create(self):
        p = Packet(PacketType.CODON, stream_id=5, sequence=42,
                   payload=b'\x01\x02\x03')
        assert p.packet_type == PacketType.CODON
        assert p.stream_id == 5
        assert p.sequence == 42
        assert p.payload == b'\x01\x02\x03'

    def test_noise_flag(self):
        p = Packet(PacketType.CODON, has_noise=True)
        assert p.has_noise is True

    def test_fragment_flag(self):
        p = Packet(PacketType.CODON, is_fragmented=True)
        assert p.is_fragmented is True


class TestPacketSerialize:
    def test_roundtrip(self):
        original = Packet(PacketType.CODON, stream_id=1, sequence=100,
                          payload=b'test payload')
        data = serialize_packet(original, pad=False)
        recovered = deserialize_packet(data)
        assert recovered is not None
        assert recovered.packet_type == original.packet_type
        assert recovered.stream_id == original.stream_id
        assert recovered.sequence == original.sequence
        assert recovered.payload == original.payload

    def test_roundtrip_with_padding(self):
        original = Packet(PacketType.CODON, stream_id=0, sequence=0,
                          payload=b'test')
        data = serialize_packet(original, pad=True)
        recovered = deserialize_packet(data)
        assert recovered is not None
        assert recovered.payload == b'test'
        # Should be padded to at least 64 bytes
        assert len(data) >= 64

    def test_bad_magic(self):
        data = struct.pack('>H', 0xBEEF) + b'\x00' * 100
        assert deserialize_packet(data) is None

    def test_bad_version(self):
        # Magic OK but version wrong
        header = struct.pack('>H B B H I H', MAGIC, 0xFF, 0, 0, 0, 4)
        data = header + b'\x00' * 4 + struct.pack('>H', 0)
        # will fail checksum
        assert deserialize_packet(data) is None

    def test_truncated(self):
        assert deserialize_packet(b'\x00\x00') is None


class TestPacketBuilders:
    def test_make_negotiate(self):
        p = make_negotiate(["weather-v1", "db-v2"])
        assert p.packet_type == PacketType.NEGOTIATE
        import json
        data = json.loads(p.payload)
        assert "weather-v1" in data['codebook_ids']

    def test_make_negotiate_ack(self):
        p = make_negotiate_ack("weather-v1", 3, os.urandom(32))
        assert p.packet_type == PacketType.NEGOTIATE_ACK

    def test_make_codon(self):
        p = make_codon(b'\x01\x02\x03\x04\x05\x06')
        assert p.packet_type == PacketType.CODON
        # new payload format: chain_index(u16) + codon_count(u8) + noise_count(u8) + codon_bytes
        assert p.payload[0:2] == b'\x00\x00'  # chain_index default 0
        assert p.payload[2] == 2  # 6 bytes / 3 = 2 codons (rough count)
        assert p.payload[3] == 0  # noise count

    def test_make_codon_with_chain_index(self):
        p = make_codon(b'\x01\x02\x03', chain_index=5)
        import struct
        chain = struct.unpack('>H', p.payload[0:2])[0]
        assert chain == 5

    def test_make_codon_with_noise(self):
        p = make_codon(b'\x01\x02\x03', noise=b'\x00\x00\x00')
        assert p.has_noise is True

    def test_make_codon_ack(self):
        p = make_codon_ack(42, chain_index=0)
        assert p.packet_type == PacketType.CODON
        assert p.is_ack is True
        import struct
        chain, ack_seq = struct.unpack('>H I', p.payload[:6])
        assert chain == 0
        assert ack_seq == 42

    def test_make_rotate(self):
        p = make_rotate(5)
        assert p.packet_type == PacketType.ROTATE
        chain_index = struct.unpack('>I', p.payload)[0]
        assert chain_index == 5

    def test_make_error(self):
        p = make_error(ErrorCode.CODON_UNKNOWN, "test error")
        assert p.packet_type == PacketType.ERROR


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
