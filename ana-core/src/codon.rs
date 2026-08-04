//! Codon encoding and decoding.
//!
//! A codon is a compact binary representation of an API operation call:
//! `[service_id: u8][operation_id: u8][template_id: u8][param_bytes...]`

use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Unsigned LEB128 varint
// ---------------------------------------------------------------------------

pub fn encode_varint(value: u64) -> Vec<u8> {
    let mut v = value;
    let mut buf = Vec::with_capacity(10);
    while v > 0x7F {
        buf.push((v as u8 & 0x7F) | 0x80);
        v >>= 7;
    }
    buf.push(v as u8);
    buf
}

pub fn decode_varint(data: &[u8]) -> Option<(u64, usize)> {
    let mut value: u64 = 0;
    let mut shift = 0u32;
    for (i, &byte) in data.iter().enumerate() {
        value |= ((byte & 0x7F) as u64) << shift;
        if byte & 0x80 == 0 {
            return Some((value, i + 1));
        }
        shift += 7;
        if shift > 63 {
            return None; // overflow
        }
    }
    None // truncated
}

// ---------------------------------------------------------------------------
// Parameter encoding
// ---------------------------------------------------------------------------

fn param_value_to_string(v: &ParamValue) -> String {
    match v {
        ParamValue::String(s) => s.clone(),
        ParamValue::Uint8(n) => n.to_string(),
        ParamValue::Uint16(n) => n.to_string(),
        ParamValue::Uint32(n) => n.to_string(),
        ParamValue::Int32(n) => n.to_string(),
        ParamValue::Float32(n) => n.to_string(),
        ParamValue::Bool(b) => b.to_string(),
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum ParamValue {
    String(String),
    Uint8(u8),
    Uint16(u16),
    Uint32(u32),
    Int32(i32),
    Float32(f32),
    Bool(bool),
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ParamType {
    String,
    Uint8,
    Uint16,
    Uint32,
    Int32,
    Float32,
    Bool,
}

impl ParamType {
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "string" => Some(ParamType::String),
            "uint8" => Some(ParamType::Uint8),
            "uint16" => Some(ParamType::Uint16),
            "uint32" => Some(ParamType::Uint32),
            "int32" => Some(ParamType::Int32),
            "float32" => Some(ParamType::Float32),
            "bool" => Some(ParamType::Bool),
            _ => None,
        }
    }
}

pub fn encode_params(params: &[ParamValue], types: &[ParamType]) -> Vec<u8> {
    let mut buf = Vec::new();
    for (val, typ) in params.iter().zip(types.iter()) {
        match (val, typ) {
            (ParamValue::String(s), ParamType::String) => {
                buf.extend_from_slice(s.as_bytes());
                buf.push(0x00); // null terminator
            }
            (ParamValue::Uint8(v), ParamType::Uint8) => buf.push(*v),
            (ParamValue::Uint16(v), ParamType::Uint16) => buf.extend_from_slice(&v.to_be_bytes()),
            (ParamValue::Uint32(v), ParamType::Uint32) => buf.extend_from_slice(&v.to_be_bytes()),
            (ParamValue::Int32(v), ParamType::Int32) => buf.extend_from_slice(&v.to_be_bytes()),
            (ParamValue::Float32(v), ParamType::Float32) => buf.extend_from_slice(&v.to_be_bytes()),
            (ParamValue::Bool(v), ParamType::Bool) => buf.push(if *v { 1 } else { 0 }),
            _ => panic!("type mismatch in encode_params"),
        }
    }
    buf
}

pub fn decode_params(data: &[u8], types: &[ParamType]) -> Option<(Vec<ParamValue>, usize)> {
    let mut results = Vec::with_capacity(types.len());
    let mut offset = 0;

    for typ in types {
        match typ {
            ParamType::String => {
                let null_pos = data[offset..].iter().position(|&b| b == 0x00)?;
                let s = String::from_utf8(data[offset..offset + null_pos].to_vec()).ok()?;
                offset += null_pos + 1;
                results.push(ParamValue::String(s));
            }
            ParamType::Uint8 => {
                if offset >= data.len() { return None; }
                results.push(ParamValue::Uint8(data[offset]));
                offset += 1;
            }
            ParamType::Uint16 => {
                if offset + 2 > data.len() { return None; }
                let v = u16::from_be_bytes([data[offset], data[offset + 1]]);
                results.push(ParamValue::Uint16(v));
                offset += 2;
            }
            ParamType::Uint32 => {
                if offset + 4 > data.len() { return None; }
                let v = u32::from_be_bytes([data[offset], data[offset+1], data[offset+2], data[offset+3]]);
                results.push(ParamValue::Uint32(v));
                offset += 4;
            }
            ParamType::Int32 => {
                if offset + 4 > data.len() { return None; }
                let v = i32::from_be_bytes([data[offset], data[offset+1], data[offset+2], data[offset+3]]);
                results.push(ParamValue::Int32(v));
                offset += 4;
            }
            ParamType::Float32 => {
                if offset + 4 > data.len() { return None; }
                let v = f32::from_be_bytes([data[offset], data[offset+1], data[offset+2], data[offset+3]]);
                results.push(ParamValue::Float32(v));
                offset += 4;
            }
            ParamType::Bool => {
                if offset >= data.len() { return None; }
                results.push(ParamValue::Bool(data[offset] != 0));
                offset += 1;
            }
        }
    }
    Some((results, offset))
}

// ---------------------------------------------------------------------------
// Codon
// ---------------------------------------------------------------------------

pub const NOOP: [u8; 3] = [0x00, 0x00, 0x00];
pub const RESERVED: [u8; 3] = [0xFF, 0xFF, 0xFF];
pub const RESPONSE_FLAG: u8 = 0x80;

#[derive(Debug, Clone)]
pub struct CodonCodec {
    // (service_id, op_id, template_id) -> (param_names, param_types)
    templates: HashMap<(u8, u8, u8), (Vec<String>, Vec<ParamType>)>,
}

impl CodonCodec {
    pub fn new() -> Self {
        CodonCodec { templates: HashMap::new() }
    }

    pub fn register(
        &mut self,
        service_id: u8,
        op_id: u8,
        template_id: u8,
        param_names: Vec<String>,
        param_types: Vec<ParamType>,
    ) {
        self.templates.insert((service_id, op_id, template_id), (param_names, param_types));
    }

    /// Encode a codon. Returns the codon bytes.
    pub fn encode(
        &self,
        service_id: u8,
        op_id: u8,
        template_id: u8,
        params: &[ParamValue],
        is_response: bool,
    ) -> Vec<u8> {
        let op_byte = if is_response { op_id | RESPONSE_FLAG } else { op_id };
        let mut buf = vec![service_id, op_byte, template_id];

        if !params.is_empty() {
            if let Some((_, types)) = self.templates.get(&(service_id, op_id, template_id)) {
                buf.extend(encode_params(params, types));
            }
        }
        buf
    }

    /// Decode a single codon. Returns (decoded_info, new_offset).
    pub fn decode(&self, data: &[u8]) -> Option<(DecodedCodon, usize)> {
        if data.len() < 3 {
            return None;
        }
        let service_id = data[0];
        let op_byte = data[1];
        let template_id = data[2];
        let is_response = op_byte & RESPONSE_FLAG != 0;
        let op_id = op_byte & !RESPONSE_FLAG;

        // Noise codon
        if service_id == 0 && op_id == 0 && template_id == 0 {
            return Some((DecodedCodon::noise(), 3));
        }

        // Reserved
        if service_id == 0xFF && op_id == 0xFF && template_id == 0xFF {
            return Some((DecodedCodon::reserved(), 3));
        }

        // Control codons
        if service_id == 0xFF {
            match op_id {
                0x04 => return Some((DecodedCodon::control("ping"), 3)),
                0x05 => return Some((DecodedCodon::control("pong"), 3)),
                0x02 => return Some((DecodedCodon::control("teardown"), 3)),
                _ => {}
            }
        }

        // Lookup template
        if let Some((names, types)) = self.templates.get(&(service_id, op_id, template_id)) {
            let (values, consumed) = decode_params(&data[3..], types)?;
            let params: HashMap<String, String> = names.iter()
                .zip(values.iter())
                .map(|(n, v)| (n.clone(), param_value_to_string(v)))
                .collect();
            Some((DecodedCodon {
                is_noise: false,
                is_response,
                is_reserved: false,
                is_control: false,
                control_type: String::new(),
                service_id,
                operation_id: op_id,
                template_id,
                params,
            }, 3 + consumed))
        } else {
            None
        }
    }

    /// Decode multiple codons from a byte slice.
    pub fn decode_multi(&self, data: &[u8]) -> Vec<DecodedCodon> {
        let mut results = Vec::new();
        let mut offset = 0;
        while offset < data.len() {
            if let Some((codon, new_offset)) = self.decode(&data[offset..]) {
                offset += new_offset;
                if !codon.is_noise {
                    results.push(codon);
                }
            } else {
                break;
            }
        }
        results
    }
}

impl Default for CodonCodec {
    fn default() -> Self { Self::new() }
}

#[derive(Debug, Clone)]
pub struct DecodedCodon {
    pub is_noise: bool,
    pub is_response: bool,
    pub is_reserved: bool,
    pub is_control: bool,
    pub control_type: String,
    pub service_id: u8,
    pub operation_id: u8,
    pub template_id: u8,
    pub params: HashMap<String, String>,
}

impl DecodedCodon {
    pub fn noise() -> Self {
        DecodedCodon {
            is_noise: true, is_response: false, is_reserved: false,
            is_control: false, control_type: String::new(),
            service_id: 0, operation_id: 0, template_id: 0,
            params: HashMap::new(),
        }
    }

    pub fn reserved() -> Self {
        DecodedCodon {
            is_noise: false, is_response: false, is_reserved: true,
            is_control: false, control_type: String::new(),
            service_id: 0xFF, operation_id: 0xFF, template_id: 0xFF,
            params: HashMap::new(),
        }
    }

    pub fn control(typ: &str) -> Self {
        DecodedCodon {
            is_noise: false, is_response: false, is_reserved: false,
            is_control: true, control_type: typ.to_string(),
            service_id: 0xFF, operation_id: 0, template_id: 0,
            params: HashMap::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_varint_small() {
        assert_eq!(encode_varint(0), vec![0]);
        assert_eq!(encode_varint(127), vec![127]);
        assert_eq!(decode_varint(&[0]), Some((0, 1)));
    }

    #[test]
    fn test_varint_two_byte() {
        assert_eq!(encode_varint(128), vec![0x80, 0x01]);
        assert_eq!(decode_varint(&[0x80, 0x01]), Some((128, 2)));
    }

    #[test]
    fn test_varint_roundtrip() {
        for v in [0, 1, 127, 128, 300, 65535, 1_000_000] {
            let enc = encode_varint(v);
            let (dec, _) = decode_varint(&enc).unwrap();
            assert_eq!(dec, v);
        }
    }

    #[test]
    fn test_encode_decode_params() {
        let params = vec![ParamValue::String("Beijing".into()), ParamValue::Uint8(7)];
        let types = vec![ParamType::String, ParamType::Uint8];
        let enc = encode_params(&params, &types);
        let (dec, off) = decode_params(&enc, &types).unwrap();
        assert_eq!(dec.len(), 2);
        assert_eq!(dec[0], ParamValue::String("Beijing".into()));
        assert_eq!(dec[1], ParamValue::Uint8(7));
    }

    #[test]
    fn test_codon_roundtrip() {
        let mut codec = CodonCodec::new();
        codec.register(1, 1, 0,
            vec!["city".into(), "days".into()],
            vec![ParamType::String, ParamType::Uint8],
        );

        let params = vec![ParamValue::String("Beijing".into()), ParamValue::Uint8(7)];
        let codon = codec.encode(1, 1, 0, &params, false);
        let (decoded, _) = codec.decode(&codon).unwrap();
        assert!(!decoded.is_noise);
        assert!(!decoded.is_response);
        assert_eq!(decoded.params.get("city").unwrap(), "Beijing");
    }

    #[test]
    fn test_noise_codon() {
        let codec = CodonCodec::new();
        let codon = vec![0x00, 0x00, 0x00];
        let (decoded, _) = codec.decode(&codon).unwrap();
        assert!(decoded.is_noise);
    }

    #[test]
    fn test_response_flag() {
        let mut codec = CodonCodec::new();
        codec.register(1, 1, 0,
            vec!["city".into(), "days".into()],
            vec![ParamType::String, ParamType::Uint8],
        );

        let params = vec![ParamValue::String("OK".into()), ParamValue::Uint8(1)];
        let codon = codec.encode(1, 1, 0, &params, true);
        let (decoded, _) = codec.decode(&codon).unwrap();
        assert!(decoded.is_response);
    }
}
