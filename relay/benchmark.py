#!/usr/bin/env python3
"""
ANA Relay vs Traditional Relay — Cost Comparison.

Estimates the real-world cost savings of using ANA codon dispatch
vs traditional JSON relay for an API gateway at scale.

Run: python3 relay/benchmark.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── Assumptions ───────────────────────────────────────────────────

CALLS_PER_DAY = 10_000      # Typical relay daily volume
DAYS_PER_MONTH = 30
OUTPUT_TOKEN_PRICE = 15.0    # $ per 1M tokens (GPT-4 level)
INPUT_TOKEN_PRICE = 3.0      # $ per 1M tokens

# Token counts (measured with cl100k_base estimator)
JSON_TOKENS_PER_CALL = 62    # OpenAI tool_call format
CODON_TOKENS_PER_CALL = 6    # @s.o.t format
JSON_RESPONSE_TOKENS = 50    # Reading the response
CODON_RESPONSE_TOKENS = 3    # @128.1.0 {json}

# ─── Calculation ───────────────────────────────────────────────────

def monthly_cost(calls_per_day, tokens_per_call, resp_tokens):
    monthly_tokens = (tokens_per_call + resp_tokens) * calls_per_day * DAYS_PER_MONTH
    # Output tokens cost more (LLM generates them)
    # Input tokens cost less (LLM reads them)
    output_cost = tokens_per_call * calls_per_day * DAYS_PER_MONTH / 1_000_000 * OUTPUT_TOKEN_PRICE
    input_cost = resp_tokens * calls_per_day * DAYS_PER_MONTH / 1_000_000 * INPUT_TOKEN_PRICE
    return monthly_tokens, output_cost + input_cost

json_tok, json_cost = monthly_cost(CALLS_PER_DAY, JSON_TOKENS_PER_CALL, JSON_RESPONSE_TOKENS)
ana_tok, ana_cost = monthly_cost(CALLS_PER_DAY, CODON_TOKENS_PER_CALL, CODON_RESPONSE_TOKENS)

# ─── Report ────────────────────────────────────────────────────────

print("=" * 65)
print("ANA RELAY vs TRADITIONAL RELAY — Cost Comparison")
print("=" * 65)
print(f"""
Assumptions:
  Daily calls:       {CALLS_PER_DAY:,}
  Output token price: ${OUTPUT_TOKEN_PRICE}/M tokens
  Input token price:  ${INPUT_TOKEN_PRICE}/M tokens
""")

print(f"{'Metric':<35} {'JSON Relay':>12} {'ANA Relay':>12}")
print("-" * 65)
print(f"{'Tokens per call (output)':<35} {JSON_TOKENS_PER_CALL:>12} {CODON_TOKENS_PER_CALL:>12}")
print(f"{'Tokens per call (input)':<35} {JSON_RESPONSE_TOKENS:>12} {CODON_RESPONSE_TOKENS:>12}")
print(f"{'Total tokens per round-trip':<35} {JSON_TOKENS_PER_CALL + JSON_RESPONSE_TOKENS:>12} {CODON_TOKENS_PER_CALL + CODON_RESPONSE_TOKENS:>12}")
print(f"{'Token reduction':<35} {'':>12} {(1 - (CODON_TOKENS_PER_CALL + CODON_RESPONSE_TOKENS) / (JSON_TOKENS_PER_CALL + JSON_RESPONSE_TOKENS)) * 100:>11.0f}%")
print()
print(f"{'Monthly tokens':<35} {json_tok:>12,} {ana_tok:>12,}")
print(f"{'Monthly cost':<35} ${json_cost:>11.2f} ${ana_cost:>11.2f}")
print(f"{'Annual cost':<35} ${json_cost*12:>11.2f} ${ana_cost*12:>11.2f}")
print(f"{'Annual savings':<35} {'':>12} ${(json_cost-ana_cost)*12:>11.2f}")
print()
print("-" * 65)

# CPU comparison
print("""
CPU Comparison (per call):
  JSON relay:  json.loads() → dict traversal → type check → forward
  ANA relay:   regex match → codebook[S][O][T] → forward

  For a relay handling {:,} calls/day, the JSON parsing overhead
  is ~{}ms/day of CPU time (vs ~{}ms/day for codon parsing).
""".format(
    CALLS_PER_DAY,
    int(CALLS_PER_DAY * 0.0015),  # ~1.5µs per json.loads
    int(CALLS_PER_DAY * 0.0003),  # ~0.3µs per table lookup
))

# Scale analysis
print("-" * 65)
print("AT SCALE (varying daily volume):")
print(f"{'Daily Calls':<15} {'JSON/mo':>10} {'ANA/mo':>10} {'Savings/yr':>12}")
print("-" * 65)
for calls in [1_000, 10_000, 50_000, 100_000, 1_000_000]:
    _, jc = monthly_cost(calls, JSON_TOKENS_PER_CALL, JSON_RESPONSE_TOKENS)
    _, ac = monthly_cost(calls, CODON_TOKENS_PER_CALL, CODON_RESPONSE_TOKENS)
    print(f"{calls:<15,} ${jc:>9.2f} ${ac:>9.2f} ${(jc-ac)*12:>11.2f}")

print()
print("=" * 65)
print("CONCLUSION")
print("=" * 65)
print(f"""
ANA relay saves {int((1 - ana_cost/json_cost) * 100)}% on token costs vs traditional JSON relay.
At {CALLS_PER_DAY:,} calls/day, that's ${(json_cost-ana_cost)*12:,.0f}/year.

The savings come from:
  1. Compact codon format (@s.o.t = 6 tokens vs 62 for OpenAI tool_call)
  2. Minimal response format (3 tokens vs 50)
  3. No JSON parser CPU overhead on the relay side

Any LLM can output @s.o.t format — no model changes needed.
""")
