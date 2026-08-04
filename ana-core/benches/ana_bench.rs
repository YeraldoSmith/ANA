use criterion::{black_box, criterion_group, criterion_main, Criterion};
use ana_core::*;

fn bench_codon_encode(c: &mut Criterion) {
    let mut codec = CodonCodec::new();
    codec.register(1, 1, 0,
        vec!["city".into(), "days".into()],
        vec![ParamType::String, ParamType::Uint8],
    );
    let params = vec![ParamValue::String("Beijing".into()), ParamValue::Uint8(7)];

    c.bench_function("codon_encode", |b| {
        b.iter(|| codec.encode(1, 1, 0, black_box(&params), false))
    });
}

fn bench_codon_decode(c: &mut Criterion) {
    let mut codec = CodonCodec::new();
    codec.register(1, 1, 0,
        vec!["city".into(), "days".into()],
        vec![ParamType::String, ParamType::Uint8],
    );
    let params = vec![ParamValue::String("Beijing".into()), ParamValue::Uint8(7)];
    let codon = codec.encode(1, 1, 0, &params, false);

    c.bench_function("codon_decode", |b| {
        b.iter(|| codec.decode(black_box(&codon)))
    });
}

fn bench_packet_roundtrip(c: &mut Criterion) {
    let codon = vec![0x01, 0x01, 0x00,
        b'B', b'e', b'i', b'j', b'i', b'n', b'g', 0x00, 0x07];

    c.bench_function("packet_roundtrip", |b| {
        b.iter(|| {
            let pkt = make_codon(black_box(&codon), 0, 0, b"", false, 0);
            let wire = serialize_packet(&pkt, None, false);
            deserialize_packet(black_box(&wire), None)
        })
    });
}

fn bench_packet_roundtrip_hmac(c: &mut Criterion) {
    let codon = vec![0x01, 0x01, 0x00,
        b'B', b'e', b'i', b'j', b'i', b'n', b'g', 0x00, 0x07];
    let key = b"0123456789abcdef0123456789abcdef";

    c.bench_function("packet_roundtrip_hmac", |b| {
        b.iter(|| {
            let pkt = make_codon(black_box(&codon), 0, 0, b"", false, 0);
            let wire = serialize_packet(&pkt, Some(key), false);
            deserialize_packet(black_box(&wire), Some(key))
        })
    });
}

fn bench_hmac_compute(c: &mut Criterion) {
    let key = b"0123456789abcdef0123456789abcdef";
    let data = b"test message for HMAC benchmark";

    c.bench_function("hmac_compute", |b| {
        b.iter(|| compute_hmac(black_box(key), black_box(data)))
    });
}

fn bench_crc16(c: &mut Criterion) {
    let data = [0u8; 64];
    c.bench_function("crc16_64b", |b| {
        b.iter(|| crc16(black_box(&data)))
    });
}

criterion_group!(benches,
    bench_codon_encode,
    bench_codon_decode,
    bench_packet_roundtrip,
    bench_packet_roundtrip_hmac,
    bench_hmac_compute,
    bench_crc16,
);
criterion_main!(benches);
