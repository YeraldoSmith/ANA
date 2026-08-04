#!/usr/bin/env python3
"""
Agent-side demo of the ANA Chain protocol.

Simulates an AI Agent using codon-based communication
to call a weather API. Compares ANA mode vs JSON mode.
"""

import socket
import time
import sys
import os

# Add parent dir to path for direct execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana import (
    Codebook, CodonEncoder, CodonDecoder,
    Packet, PacketType, serialize_packet, deserialize_packet,
    Session, SessionState,
    Negotiator,
)
from ana.transport import UDPSender, UDPReceiver, NoiseGenerator
from ana.packet import make_codon


def load_codebook():
    """Load the codebook from YAML."""
    yaml_path = os.path.join(os.path.dirname(__file__), 'weather_service.yaml')
    return Codebook.from_yaml_file(yaml_path)


def demo_negotiation():
    """Demonstrate the negotiation phase."""
    print("=" * 60)
    print("PHASE 1: NEGOTIATION")
    print("=" * 60)

    codebook = load_codebook()
    negotiator = Negotiator({'weather-v1': codebook})

    print(f"  Agent supports codebooks: ['weather-v1']")
    print(f"  Codebook: {codebook.version.codebook_id} v{codebook.version.version}")
    print(f"  Seed hash: {codebook.version.seed_hash.hex()[:16]}...")
    print(f"  Services: {list(codebook.services.keys())}")

    return codebook


def demo_codon_encoding(codebook):
    """Demonstrate codon encoding vs JSON."""
    print()
    print("=" * 60)
    print("PHASE 2: CODON ENCODING (Agent side)")
    print("=" * 60)

    encoder = CodonEncoder(codebook)

    # Example calls
    calls = [
        ("get_forecast by city", 1, 1, 0, ["Beijing", 7], ["string", "uint8"]),
        ("get_current", 1, 2, 0, ["Tokyo"], ["string"]),
        ("get_alerts", 2, 1, 0, ["Asia", "severe"], ["string", "string"]),
    ]

    for label, svc, op, tpl, params, types in calls:
        codon = encoder.encode(svc, op, tpl, params)
        json_equiv = f'{{"service": "{codebook.get_service(svc).name}", '
        json_equiv += f'"operation": "{codebook.get_operation(svc, op).name}", '
        json_equiv += f'"params": {dict(zip(codebook.get_template(svc, op, tpl).params, params))}}}'

        print(f"\n  {label}:")
        print(f"    Codon bytes ({len(codon)}):  {codon.hex()}")
        print(f"    JSON equiv ({len(json_equiv)}):  {json_equiv}")
        print(f"    Size reduction: {len(json_equiv) / len(codon):.1f}x")

    return encoder


def demo_codon_decoding(codebook, encoder):
    """Demonstrate codon decoding with noise."""
    print()
    print("=" * 60)
    print("PHASE 3: CODON DECODING (API side)")
    print("=" * 60)

    decoder = CodonDecoder(codebook)

    # Encode some codons with noise mixed in
    real_codons = encoder.encode_multi([
        (1, 1, 0, ["Shanghai", 3], False),
        (2, 1, 0, ["Europe", "all"], False),
    ])
    noise = encoder.make_noise(2)
    # Interleave: real, noise, real, noise
    mixed = (real_codons[:len(real_codons)//2] + noise[:3] +
             real_codons[len(real_codons)//2:] + noise[3:])

    print(f"  Mixed payload ({len(mixed)} bytes): {mixed.hex()}")
    print()

    decoded = decoder.decode_multi(mixed)
    for i, d in enumerate(decoded):
        if d.get('is_noise'):
            print(f"  [{i}] NOISE — discarded")
        elif d.get('error'):
            print(f"  [{i}] ERROR: {d['error']}")
        else:
            print(f"  [{i}] {d['service_name']}.{d['operation_name']}"
                  f"({d['params']}) — {d['template_description']}")

    return decoder


def demo_session_lifecycle(codebook):
    """Demonstrate session state transitions."""
    print()
    print("=" * 60)
    print("PHASE 4: SESSION LIFECYCLE")
    print("=" * 60)

    import os
    from ana.codebook import CodebookVersion, derive_master_seed

    session = Session(side="agent")
    print(f"  Initial state: {session.state.value}")

    # Negotiate
    session.start_negotiation()
    print(f"  After start_negotiation: {session.state.value}")

    # Establish
    session_nonce = os.urandom(32)
    session.establish(codebook, codebook.version, session_nonce)
    print(f"  After establish: {session.state.value}")
    print(f"  Master seed derived: {session.master_seed.hex()[:16]}...")

    # Simulate traffic
    encoder = CodonEncoder(codebook)
    for i in range(5):
        seq = session.next_send_seq(0)
        print(f"  Send seq={seq}")
        session.record_send()

    print(f"  Packets sent: {session.packets_sent}")
    print(f"  Chain packets: {session.current_chain_packets}")

    # Rotate
    session.rotate(1)
    print(f"  After rotate to chain 1: {session.state.value}")
    print(f"  Chain packets reset to: {session.current_chain_packets}")

    # Fallback
    session.fallback()
    print(f"  After fallback: {session.state.value}")

    # Recover
    session.recover_from_fallback(codebook, codebook.version, os.urandom(32))
    print(f"  After recover: {session.state.value}")

    # Summary
    print()
    print(f"  Session summary: {session.summary()}")


def demo_performance_comparison():
    """Compare ANA vs JSON performance."""
    print()
    print("=" * 60)
    print("PHASE 5: PERFORMANCE COMPARISON")
    print("=" * 60)

    codebook = load_codebook()
    encoder = CodonEncoder(codebook)

    # Simulate 1000 calls
    calls = []
    for i in range(1000):
        cities = ["Beijing", "Tokyo", "London", "NYC", "Paris", "Dubai", "Sydney"]
        city = cities[i % len(cities)]
        calls.append((1, 1, 0, [city, i % 7 + 1], ["string", "uint8"]))

    # ANA encoding
    start = time.perf_counter()
    ana_total_bytes = 0
    for svc, op, tpl, params, types in calls:
        codon = encoder.encode(svc, op, tpl, params)
        ana_total_bytes += len(codon) + 14  # +14 for packet overhead
    ana_time = time.perf_counter() - start

    # JSON encoding
    start = time.perf_counter()
    import json
    json_total_bytes = 0
    for svc, op, tpl, params, types in calls:
        j = json.dumps({
            "service": codebook.get_service(svc).name,
            "operation": codebook.get_operation(svc, op).name,
            "params": dict(zip(codebook.get_template(svc, op, tpl).params, params)),
        })
        json_total_bytes += len(j) + 200  # HTTP/TLS overhead estimate
    json_time = time.perf_counter() - start

    print(f"\n  1000 operations:")
    print(f"    ANA time:     {ana_time*1000:.2f} ms")
    print(f"    JSON time:    {json_time*1000:.2f} ms")
    print(f"    ANA bytes:    {ana_total_bytes:,}")
    print(f"    JSON bytes:   {json_total_bytes:,}")
    print(f"    Time ratio:   {json_time/ana_time:.1f}x faster with ANA")
    print(f"    Bytes ratio:  {json_total_bytes/ana_total_bytes:.1f}x smaller with ANA")

    # Token estimate
    avg_json_tokens = json_total_bytes / 1000 / 4  # ~4 chars per token
    ana_tokens = 3  # codon header is 3 special tokens
    print(f"\n  Token estimate (per call):")
    print(f"    JSON mode: ~{avg_json_tokens:.0f} tokens")
    print(f"    ANA mode:  ~{ana_tokens} tokens")
    print(f"    Reduction: ~{avg_json_tokens/ana_tokens:.0f}x")


def main():
    print("ANA Chain Protocol — Agent Demo")
    print()

    codebook = demo_negotiation()
    encoder = demo_codon_encoding(codebook)
    decoder = demo_codon_decoding(codebook, encoder)
    demo_session_lifecycle(codebook)
    demo_performance_comparison()

    print()
    print("=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
