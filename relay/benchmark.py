#!/usr/bin/env python3
"""
ANA Relay vs Traditional Relay -- Cost Comparison.

Every number in this script comes from token_counter.count() applied
to real text strings. No hardcoded token counts.

Run: python3 relay/benchmark.py
"""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from relay.token_counter import count, label as token_label

# Measured from real text, not hardcoded
JSON_CALL = json.dumps({
    "id": "call_abc", "type": "function",
    "function": {"name": "weather.get_forecast",
                 "arguments": '{"city":"Beijing","days":7}'}
}, ensure_ascii=False)

CODON_CALL = "@1.1.0 Beijing 7"

RESPONSE_DATA = json.dumps({
    "city": "Beijing", "days": 7,
    "forecast": [{"day": 1, "high": 22, "low": 12, "condition": "Sunny"},
                 {"day": 2, "high": 24, "low": 14, "condition": "Cloudy"}]
}, ensure_ascii=False)

JSON_RESP = json.dumps({
    "id": "call_abc", "type": "function",
    "function": {"name": "weather.get_forecast", "arguments": RESPONSE_DATA}
}, ensure_ascii=False)

CODON_RESP = f"@128.1.0 {RESPONSE_DATA}"

JSON_PROMPT = """You have access to the following functions:
- get_forecast(city, days): get weather forecast
- get_current(city): get current weather
- get_alerts(region, severity): get weather alerts
Call them using the function calling format."""

CODON_PROMPT = """When calling functions, use format: @service.operation.template param1 param2
Available: @1.1.0 <city> <days> @1.2.0 <city> @2.1.0 <region> <severity>"""

# Count everything
json_call_tok = count(JSON_CALL)
codon_call_tok = count(CODON_CALL)
resp_data_tok = count(RESPONSE_DATA)   # same for both
json_resp_tok = count(JSON_RESP)
codon_resp_tok = count(CODON_RESP)
json_ctx_tok = count(JSON_PROMPT)
codon_ctx_tok = count(CODON_PROMPT)

CALLS_PER_DAY = 10_000
CONVOS_PER_DAY = 2_000   # 5 calls per conversation
PRICE_OUT = 15.0
PRICE_IN = 3.0
DAYS = 30

# Report
print(f"ANA Relay Token Measurement ({token_label()})")
print("=" * 60)
print()
print("SINGLE CALL: get_forecast(city=Beijing, days=7)")
print("-" * 60)
print(f"{'':<25} {'JSON':>12} {'ANA':>12} {'Note'}")
print(f"{'Call output tokens':<25} {json_call_tok:>12} {codon_call_tok:>12}")
print(f"{'Response tokens':<25} {json_resp_tok:>12} {codon_resp_tok:>12}  same data inside")
print(f"{'Context (amortized)':<25} {json_ctx_tok:>12} {codon_ctx_tok:>12}")
print(f"{'Call reduction':<25} {'':>12} {(1-codon_call_tok/json_call_tok)*100:>11.0f}%")
print()
print("THREE-SEGMENT TOTAL (per call, context amortized over 5 calls)")
print("-" * 60)
json_call_total = json_call_tok + json_resp_tok + json_ctx_tok / 5
codon_call_total = codon_call_tok + codon_resp_tok + codon_ctx_tok / 5
print(f"  JSON total:  {json_call_total:.0f} tokens/call")
print(f"  ANA total:   {codon_call_total:.0f} tokens/call")
print(f"  Reduction:   {(1-codon_call_total/json_call_total)*100:.0f}%")
print()
print("COST MODEL (10,000 calls/day)")
print("-" * 60)
json_out_cost = json_call_tok * CALLS_PER_DAY * DAYS / 1e6 * PRICE_OUT
codon_out_cost = codon_call_tok * CALLS_PER_DAY * DAYS / 1e6 * PRICE_OUT
json_in_cost = json_resp_tok * CALLS_PER_DAY * DAYS / 1e6 * PRICE_IN
codon_in_cost = codon_resp_tok * CALLS_PER_DAY * DAYS / 1e6 * PRICE_IN
json_ctx_cost = json_ctx_tok * CONVOS_PER_DAY * DAYS / 1e6 * PRICE_IN
codon_ctx_cost = codon_ctx_tok * CONVOS_PER_DAY * DAYS / 1e6 * PRICE_IN
json_total_cost = json_out_cost + json_in_cost + json_ctx_cost
codon_total_cost = codon_out_cost + codon_in_cost + codon_ctx_cost
print(f"  JSON monthly:  ${json_total_cost:.2f}")
print(f"  ANA monthly:   ${codon_total_cost:.2f}")
print(f"  Monthly save:  ${json_total_cost - codon_total_cost:.2f}")
print(f"  Annual save:   ${(json_total_cost - codon_total_cost) * 12:.2f}")
print()
print("NOTE: Response data tokens are identical (same JSON payload).")
print("      ANA saves on call-side format + response wrapper only.")
print("      Previous 90% claim was algorithm error (assumed response")
print("      data shrinks — it does not). Correct total: ~{}%."
      .format(round((1-codon_call_total/json_call_total)*100)))
