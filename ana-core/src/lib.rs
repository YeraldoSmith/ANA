//! ANA Chain Protocol — native Rust implementation.
//!
//! A codon-based communication protocol for AI Agent <-> API communication.

pub mod codon;
pub mod packet;

// Re-exports
pub use codon::{CodonCodec, DecodedCodon, ParamType, ParamValue, encode_varint, decode_varint};
pub use packet::{
    Packet, PacketType,
    serialize_packet, deserialize_packet,
    make_codon, make_codon_ack, parse_codon_payload,
    crc16, compute_hmac, verify_hmac,
    MAGIC, HEADER_SIZE, CRC_SIZE, HMAC_SIZE, PACKET_OVERHEAD,
};
