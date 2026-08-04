//! ANA Chain packet serialization.
//!
//! Packet format:
//!   [magic: u16][version: u8][flags: u8][stream_id: u16][seq: u32]
//!   [payload_len: u16][payload: bytes][crc16: u16][hmac?: u8*16][padding]

use hmac::{Hmac, Mac};
use sha2::Sha256;

pub const MAGIC: u16 = 0xA7A7;
pub const PROTOCOL_VERSION: u8 = 0x01;
pub const HEADER_SIZE: usize = 12;
pub const CRC_SIZE: usize = 2;
pub const HMAC_SIZE: usize = 16;
pub const PACKET_OVERHEAD: usize = HEADER_SIZE + CRC_SIZE; // 14

pub const ALLOWED_SIZES: &[usize] = &[64, 128, 256, 512, 1024];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum PacketType {
    Negotiate = 0x00,
    NegotiateAck = 0x01,
    NegotiateConfirm = 0x02,
    Codon = 0x03,
    Rotate = 0x04,
    RotateAck = 0x05,
    Error = 0x06,
    Fallback = 0x07,
}

impl PacketType {
    pub fn from_u8(v: u8) -> Option<Self> {
        match v {
            0x00 => Some(Self::Negotiate),
            0x01 => Some(Self::NegotiateAck),
            0x02 => Some(Self::NegotiateConfirm),
            0x03 => Some(Self::Codon),
            0x04 => Some(Self::Rotate),
            0x05 => Some(Self::RotateAck),
            0x06 => Some(Self::Error),
            0x07 => Some(Self::Fallback),
            _ => None,
        }
    }
}

// Flags bit layout
const FLAG_HAS_NOISE: u8 = 0x08;
const FLAG_IS_FRAGMENTED: u8 = 0x10;
const FLAG_IS_ACK: u8 = 0x20;

#[derive(Debug, Clone)]
pub struct Packet {
    pub packet_type: PacketType,
    pub flags: u8,
    pub stream_id: u16,
    pub sequence: u32,
    pub payload: Vec<u8>,
}

impl Packet {
    pub fn new(packet_type: PacketType, stream_id: u16, sequence: u32,
               payload: Vec<u8>, has_noise: bool, is_fragmented: bool, is_ack: bool) -> Self {
        let mut flags = packet_type as u8;
        if has_noise { flags |= FLAG_HAS_NOISE; }
        if is_fragmented { flags |= FLAG_IS_FRAGMENTED; }
        if is_ack { flags |= FLAG_IS_ACK; }
        Packet { packet_type, flags, stream_id, sequence, payload }
    }

    pub fn has_noise(&self) -> bool { self.flags & FLAG_HAS_NOISE != 0 }
    pub fn is_fragmented(&self) -> bool { self.flags & FLAG_IS_FRAGMENTED != 0 }
    pub fn is_ack(&self) -> bool { self.flags & FLAG_IS_ACK != 0 }
}

// ---------------------------------------------------------------------------
// CRC-16
// ---------------------------------------------------------------------------

/// CRC-16/CCITT (polynomial 0x1021, initial 0xFFFF).
/// Matches the Python reference implementation.
pub fn crc16(data: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;
    for &byte in data {
        crc ^= (byte as u16) << 8;
        for _ in 0..8 {
            if crc & 0x8000 != 0 {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    crc
}

// ---------------------------------------------------------------------------
// HMAC
// ---------------------------------------------------------------------------

type HmacSha256 = Hmac<Sha256>;

pub fn compute_hmac(key: &[u8], data: &[u8]) -> Vec<u8> {
    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC key");
    mac.update(data);
    mac.finalize().into_bytes()[..HMAC_SIZE].to_vec()
}

pub fn verify_hmac(key: &[u8], data: &[u8], tag: &[u8]) -> bool {
    let expected = compute_hmac(key, data);
    // constant-time comparison
    if expected.len() != tag.len() { return false; }
    let mut diff = 0u8;
    for (a, b) in expected.iter().zip(tag.iter()) {
        diff |= a ^ b;
    }
    diff == 0
}

// ---------------------------------------------------------------------------
// Serialization
// ---------------------------------------------------------------------------

fn pad_to_allowed(data: &mut Vec<u8>) {
    for &size in ALLOWED_SIZES {
        if size >= data.len() {
            let needed = size - data.len();
            if needed > 0 {
                // Simple zero padding (production would use random bytes)
                data.resize(data.len() + needed, 0);
            }
            return;
        }
    }
}

pub fn serialize_packet(packet: &Packet, hmac_key: Option<&[u8]>, pad: bool) -> Vec<u8> {
    let mut data = Vec::with_capacity(128);

    // Header
    data.extend_from_slice(&MAGIC.to_be_bytes());
    data.push(PROTOCOL_VERSION);
    data.push(packet.flags);
    data.extend_from_slice(&packet.stream_id.to_be_bytes());
    data.extend_from_slice(&packet.sequence.to_be_bytes());
    data.extend_from_slice(&(packet.payload.len() as u16).to_be_bytes());

    // Payload
    data.extend_from_slice(&packet.payload);

    // CRC-16 over header + payload
    let cksum = crc16(&data);
    data.extend_from_slice(&cksum.to_be_bytes());

    // Optional HMAC
    if let Some(key) = hmac_key {
        let hmac_tag = compute_hmac(key, &data);
        data.extend_from_slice(&hmac_tag);
    }

    if pad {
        pad_to_allowed(&mut data);
    }

    data
}

pub fn deserialize_packet(data: &[u8], hmac_key: Option<&[u8]>) -> Option<Packet> {
    let min_len = HEADER_SIZE + CRC_SIZE + if hmac_key.is_some() { HMAC_SIZE } else { 0 };
    if data.len() < min_len {
        return None;
    }

    let magic = u16::from_be_bytes([data[0], data[1]]);
    if magic != MAGIC { return None; }

    let version = data[2];
    if version != PROTOCOL_VERSION { return None; }

    let flags = data[3];
    let stream_id = u16::from_be_bytes([data[4], data[5]]);
    let sequence = u32::from_be_bytes([data[6], data[7], data[8], data[9]]);
    let payload_len = u16::from_be_bytes([data[10], data[11]]) as usize;

    let total_needed = HEADER_SIZE + payload_len + CRC_SIZE
        + if hmac_key.is_some() { HMAC_SIZE } else { 0 };
    if data.len() < total_needed { return None; }

    // Verify CRC-16
    let crc_offset = HEADER_SIZE + payload_len;
    let expected_crc = crc16(&data[..crc_offset]);
    let actual_crc = u16::from_be_bytes([data[crc_offset], data[crc_offset + 1]]);
    if expected_crc != actual_crc { return None; }

    // Verify HMAC if present
    if let Some(key) = hmac_key {
        let hmac_offset = crc_offset + CRC_SIZE;
        let signed_data = &data[..hmac_offset];
        let hmac_tag = &data[hmac_offset..hmac_offset + HMAC_SIZE];
        if !verify_hmac(key, signed_data, hmac_tag) { return None; }
    }

    let packet_type = PacketType::from_u8(flags & 0x07)?;
    let payload = data[HEADER_SIZE..HEADER_SIZE + payload_len].to_vec();

    Some(Packet::new(
        packet_type, stream_id, sequence, payload,
        flags & FLAG_HAS_NOISE != 0,
        flags & FLAG_IS_FRAGMENTED != 0,
        flags & FLAG_IS_ACK != 0,
    ))
}

// ---------------------------------------------------------------------------
// Packet builders
// ---------------------------------------------------------------------------

pub fn make_codon(codon_bytes: &[u8], stream_id: u16, sequence: u32,
                  noise: &[u8], fragmented: bool, chain_index: u16) -> Packet {
    let codon_count = (codon_bytes.len() / 3) as u8;
    let noise_count = (noise.len() / 3) as u8;

    let mut payload = Vec::with_capacity(4 + codon_bytes.len() + noise.len());
    payload.extend_from_slice(&chain_index.to_be_bytes());
    payload.push(codon_count);
    payload.push(noise_count);
    payload.extend_from_slice(codon_bytes);
    payload.extend_from_slice(noise);

    let has_noise = noise_count > 0;
    Packet::new(PacketType::Codon, stream_id, sequence, payload,
                has_noise, fragmented, false)
}

pub fn make_codon_ack(ack_sequence: u32, chain_index: u16,
                      stream_id: u16, send_seq: u32) -> Packet {
    let mut payload = Vec::with_capacity(6);
    payload.extend_from_slice(&chain_index.to_be_bytes());
    payload.extend_from_slice(&ack_sequence.to_be_bytes());
    Packet::new(PacketType::Codon, stream_id, send_seq, payload,
                false, false, true)
}

/// Parse a CODON payload into its components.
pub fn parse_codon_payload(payload: &[u8]) -> Option<(u16, u8, u8, Vec<u8>, Vec<u8>)> {
    if payload.len() < 4 { return None; }
    let chain_index = u16::from_be_bytes([payload[0], payload[1]]);
    let codon_count = payload[2];
    let noise_count = payload[3];
    let body = &payload[4..];
    let noise_len = noise_count as usize * 3;
    if noise_len > 0 && noise_len <= body.len() {
        let codon_bytes = body[..body.len() - noise_len].to_vec();
        let noise_bytes = body[body.len() - noise_len..].to_vec();
        Some((chain_index, codon_count, noise_count, codon_bytes, noise_bytes))
    } else {
        Some((chain_index, codon_count, noise_count, body.to_vec(), vec![]))
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_crc16_known() {
        // CRC-16/CCITT of "123456789" = 0x29B1
        assert_eq!(crc16(b"123456789"), 0x29B1);
    }

    #[test]
    fn test_serialize_roundtrip() {
        let pkt = make_codon(b"\x01\x02\x03\x04\x05\x06", 0, 0, b"", false, 0);
        let wire = serialize_packet(&pkt, None, false);
        let recovered = deserialize_packet(&wire, None).unwrap();
        assert_eq!(recovered.packet_type, PacketType::Codon);
        assert_eq!(recovered.payload, pkt.payload);
    }

    #[test]
    fn test_serialize_with_hmac() {
        let key = b"0123456789abcdef0123456789abcdef";
        let pkt = make_codon(b"\x01\x02\x03", 0, 0, b"", false, 0);
        let wire = serialize_packet(&pkt, Some(key), false);
        let recovered = deserialize_packet(&wire, Some(key)).unwrap();
        assert_eq!(recovered.payload, pkt.payload);
    }

    #[test]
    fn test_hmac_tamper_detection() {
        let key = b"0123456789abcdef0123456789abcdef";
        let pkt = make_codon(b"\x01\x02\x03", 0, 0, b"", false, 0);
        let mut wire = serialize_packet(&pkt, Some(key), false);
        wire[HEADER_SIZE] ^= 0xFF;
        assert!(deserialize_packet(&wire, Some(key)).is_none());
    }

    #[test]
    fn test_parse_codon_payload() {
        let pkt = make_codon(b"\x01\x02\x03\x04\x05\x06", 0, 0, b"", false, 5);
        let (chain, cnt, ncnt, codons, noise) = parse_codon_payload(&pkt.payload).unwrap();
        assert_eq!(chain, 5);
        assert_eq!(cnt, 2); // 6 bytes / 3
        assert_eq!(ncnt, 0);
        assert_eq!(codons.len(), 6);
        assert!(noise.is_empty());
    }

    #[test]
    fn test_ack_packet() {
        let pkt = make_codon_ack(42, 0, 0, 0);
        assert!(pkt.is_ack());
        assert_eq!(pkt.packet_type, PacketType::Codon);
    }
}
