#!/usr/bin/env python3
"""
Token count benchmark: ANA codons vs JSON for LLM function calling.

Estimates the token savings when using ANA's binary codons
instead of JSON function call representations.
"""

import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana import Codebook, CodonEncoder, CodonDecoder


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 characters per token (English text)."""
    return max(1, len(text) // 4)


def estimate_json_tokens(obj: dict) -> int:
    """Estimate tokens for a JSON function call representation.

    This includes both the JSON text itself and the typical
    whitespace/formatting overhead in context windows.
    """
    compact = json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
    pretty = json.dumps(obj, ensure_ascii=False, indent=2)
    # In practice, LLMs see something in between
    avg_len = (len(compact) + len(pretty)) // 2
    return estimate_tokens(compact)


def run_benchmark():
    yaml_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             'examples', 'weather_service.yaml')
    codebook = Codebook.from_yaml_file(yaml_path)
    encoder = CodonEncoder(codebook)

    # Define test operations
    test_cases = [
        {
            'name': 'get_forecast (short city, default days)',
            'codon': (1, 1, 0, ['NYC', 7]),
            'json': {'function': 'get_forecast', 'city': 'NYC', 'days': 7},
        },
        {
            'name': 'get_forecast (long city, many days)',
            'codon': (1, 1, 0, ['Ulaanbaatar', 14]),
            'json': {'function': 'get_forecast', 'city': 'Ulaanbaatar', 'days': 14},
        },
        {
            'name': 'get_forecast (coordinates)',
            'codon': (1, 1, 1, [35.6895, 139.6917, 5]),
            'json': {'function': 'get_forecast', 'lat': 35.6895, 'lon': 139.6917, 'days': 5, 'units': 'imperial'},
        },
        {
            'name': 'get_current',
            'codon': (1, 2, 0, ['Tokyo']),
            'json': {'function': 'get_current', 'city': 'Tokyo'},
        },
        {
            'name': 'get_alerts (all)',
            'codon': (2, 1, 0, ['North America', 'all']),
            'json': {'function': 'get_alerts', 'region': 'North America', 'severity': 'all'},
        },
        {
            'name': 'get_alerts (severe only)',
            'codon': (2, 1, 0, ['Europe', 'severe']),
            'json': {'function': 'get_alerts', 'region': 'Europe', 'severity': 'severe'},
        },
        {
            'name': 'complex nested call',
            'codon': (2, 1, 0, ['Asia-Pacific', 'severe']),
            'json': {
                'function': 'get_alerts',
                'parameters': {
                    'region': 'Asia-Pacific',
                    'severity': 'severe',
                    'options': {'include_expired': False, 'limit': 50}
                }
            },
        },
    ]

    print("=" * 70)
    print("TOKEN COUNT BENCHMARK: ANA Codon vs JSON Function Calling")
    print("=" * 70)
    print()

    total_json_tokens = 0
    total_ana_tokens = 0
    total_json_bytes = 0
    total_ana_bytes = 0

    for tc in test_cases:
        svc, op, tpl, params = tc['codon']
        codon_bytes = encoder.encode(svc, op, tpl, params)
        json_tokens = estimate_json_tokens(tc['json'])
        ana_tokens = 3  # codon header as special tokens

        json_bytes = len(json.dumps(tc['json'], ensure_ascii=False))
        ana_bytes = len(codon_bytes)

        total_json_tokens += json_tokens
        total_ana_tokens += ana_tokens
        total_json_bytes += json_bytes
        total_ana_bytes += ana_bytes

        print(f"  {tc['name']}:")
        print(f"    JSON: {json_bytes}B → ~{json_tokens} tokens")
        print(f"    ANA:  {ana_bytes}B → ~{ana_tokens} tokens")
        print(f"    Token savings: {json_tokens - ana_tokens} tokens ({(1 - ana_tokens/json_tokens)*100:.0f}%)")
        print(f"    Byte savings:  {json_bytes - ana_bytes} bytes ({(1 - ana_bytes/json_bytes)*100:.0f}%)")
        print()

    print("─" * 70)
    print(f"  TOTALS ({len(test_cases)} operations):")
    print(f"    JSON tokens: {total_json_tokens}  |  ANA tokens: {total_ana_tokens}")
    print(f"    JSON bytes:  {total_json_bytes}  |  ANA bytes:  {total_ana_bytes}")
    print(f"    Token reduction: {(1 - total_ana_tokens/total_json_tokens)*100:.0f}%")
    print(f"    Byte reduction:  {(1 - total_ana_bytes/total_json_bytes)*100:.0f}%")
    print()

    # Cost estimate
    print("─" * 70)
    print("  COST ESTIMATE (1000 calls/day, 30 days):")
    calls_per_month = 1000 * 30
    json_tokens_per_month = total_json_tokens / len(test_cases) * calls_per_month
    ana_tokens_per_month = total_ana_tokens / len(test_cases) * calls_per_month

    # Pricing ($3/M input, $15/M output — model dependent)
    input_price_per_m = 3.0
    output_price_per_m = 15.0
    json_cost = (json_tokens_per_month / 1_000_000) * output_price_per_m
    ana_cost = (ana_tokens_per_month / 1_000_000) * output_price_per_m

    print(f"    Total calls: {calls_per_month:,}")
    print(f"    JSON token cost: ${json_cost:.2f}")
    print(f"    ANA token cost:  ${ana_cost:.2f}")
    print(f"    Monthly savings: ${json_cost - ana_cost:.2f}")
    print(f"    Annual savings:  ${(json_cost - ana_cost) * 12:.2f}")

    print()
    print("=" * 70)


if __name__ == '__main__':
    run_benchmark()
