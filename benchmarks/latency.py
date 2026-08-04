#!/usr/bin/env python3
"""
End-to-end latency benchmark: ANA codons vs JSON.

Measures encoding, transmission, and decoding latency
for both ANA and JSON modes.
"""

import json
import sys
import os
import time
import statistics

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana import Codebook, CodonEncoder, CodonDecoder
from ana.packet import (
    Packet, PacketType, serialize_packet, deserialize_packet,
    make_codon, make_rotate, make_rotate_ack, make_error,
    HEADER_SIZE, PACKET_OVERHEAD,
)
from ana.session import Session, SessionConfig
from ana.codebook import CodebookVersion


def benchmark_encoding():
    """Benchmark codon encoding vs JSON serialization."""
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             'examples', 'weather_service.yaml')
    codebook = Codebook.from_yaml_file(yaml_path)
    encoder = CodonEncoder(codebook)

    calls = []
    cities = ["Beijing", "Tokyo", "London", "NYC", "Paris", "Dubai", "Sydney",
              "Mumbai", "Singapore", "Seoul", "Berlin", "Moscow", "Cairo", "Lagos"]
    for i in range(10000):
        city = cities[i % len(cities)]
        calls.append((1, 1, 0, [city, (i % 14) + 1]))

    # Benchmark ANA encoding
    iterations = 100
    ana_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        for svc, op, tpl, params in calls:
            encoder.encode(svc, op, tpl, params)
        ana_times.append(time.perf_counter() - start)

    # Benchmark JSON encoding
    json_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        for svc, op, tpl, params in calls:
            json.dumps({
                "function": codebook.get_operation(svc, op).name,
                "params": dict(zip(codebook.get_template(svc, op, tpl).params, params)),
            }, ensure_ascii=False)
        json_times.append(time.perf_counter() - start)

    return {
        'name': 'Encoding (10000 calls)',
        'ana_mean_ms': statistics.mean(ana_times) * 1000,
        'ana_p50_ms': statistics.median(ana_times) * 1000,
        'json_mean_ms': statistics.mean(json_times) * 1000,
        'json_p50_ms': statistics.median(json_times) * 1000,
    }


def benchmark_decoding():
    """Benchmark codon decoding vs JSON parsing."""
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             'examples', 'weather_service.yaml')
    codebook = Codebook.from_yaml_file(yaml_path)
    encoder = CodonEncoder(codebook)
    decoder = CodonDecoder(codebook)

    # Pre-generate encoded data
    codon_payloads = []
    json_payloads = []
    cities = ["Beijing", "Tokyo", "London", "NYC", "Paris"]
    for city in cities:
        for days in [1, 3, 5, 7, 14]:
            codon_payloads.append(encoder.encode(1, 1, 0, [city, days]))
            json_payloads.append(json.dumps({
                "function": "get_forecast",
                "city": city,
                "days": days,
            }, ensure_ascii=False).encode('utf-8'))

    iterations = 5000

    # Benchmark ANA decoding
    ana_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        for payload in codon_payloads:
            decoder.decode(payload)
        ana_times.append(time.perf_counter() - start)

    # Benchmark JSON decoding
    json_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        for payload in json_payloads:
            json.loads(payload.decode('utf-8'))
        json_times.append(time.perf_counter() - start)

    return {
        'name': f'Decoding ({len(codon_payloads)} messages)',
        'ana_mean_us': statistics.mean(ana_times) * 1_000_000 / len(codon_payloads),
        'json_mean_us': statistics.mean(json_times) * 1_000_000 / len(json_payloads),
    }


def benchmark_packet_roundtrip():
    """Benchmark full packet serialize → deserialize roundtrip."""
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             'examples', 'weather_service.yaml')
    codebook = Codebook.from_yaml_file(yaml_path)
    encoder = CodonEncoder(codebook)

    codon_bytes = encoder.encode(1, 1, 0, ["Beijing", 7])

    iterations = 10000

    # ANA packet roundtrip
    ana_times = []
    for i in range(iterations):
        start = time.perf_counter()
        packet = make_codon(codon_bytes, stream_id=0, seq=i)
        wire = serialize_packet(packet, pad=True)
        recovered = deserialize_packet(wire)
        ana_times.append(time.perf_counter() - start)

    return {
        'name': f'Packet round-trip',
        'ana_mean_us': statistics.mean(ana_times) * 1_000_000,
        'ana_p50_us': statistics.median(ana_times) * 1_000_000,
    }


def print_benchmark(result):
    name = result.pop('name')
    print(f"\n  {name}:")
    for key, val in result.items():
        if 'mean' in key or 'p50' in key:
            unit = 'us' if 'us' in key else 'ms'
            print(f"    {key}: {val:.3f} {unit}")
        elif 'ratio' in key:
            print(f"    {key}: {val:.1f}x")
        else:
            print(f"    {key}: {val}")


def main():
    print("=" * 70)
    print("LATENCY BENCHMARK: ANA Codon vs JSON")
    print("=" * 70)

    results = []

    print("\n" + "─" * 70)
    results.append(benchmark_encoding())
    print_benchmark(results[-1])

    print("\n" + "─" * 70)
    results.append(benchmark_decoding())
    print_benchmark(results[-1])

    print("\n" + "─" * 70)
    results.append(benchmark_packet_roundtrip())
    print_benchmark(results[-1])

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    summaries = [
        ("Encoding", results[0]),
        ("Decoding (per msg)", results[1]),
        ("Packet round-trip", results[2]),
    ]
    for name, r in summaries:
        if 'ana_mean_ms' in r and 'json_mean_ms' in r:
            ratio = r['json_mean_ms'] / r['ana_mean_ms']
            print(f"  {name}: ANA is {ratio:.1f}x faster than JSON")
        elif 'ana_mean_us' in r and 'json_mean_us' in r:
            ratio = r['json_mean_us'] / r['ana_mean_us']
            direction = "faster" if ratio > 1 else "slower"
            print(f"  {name}: ANA is {ratio:.1f}x {direction} than JSON")
        elif 'ana_mean_us' in r:
            print(f"  {name}: {r['ana_mean_us']:.2f} µs (ANA only)")

    print()
    print("  Note: Real-world savings are larger because ANA eliminates")
    print("  LLM token generation time (50-100ms per call), which dwarfs")
    print("  encoding/decoding time.")

    print()
    print("=" * 70)


if __name__ == '__main__':
    main()
