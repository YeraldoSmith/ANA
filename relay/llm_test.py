#!/usr/bin/env python3
"""
Test: Will LLMs actually output @s.o.t codon format?

Two modes:
  - With API key:  python3 relay/llm_test.py YOUR_ANTHROPIC_API_KEY
  - Simulated:     python3 relay/llm_test.py --simulate

Tests whether an LLM, given a system prompt describing @s.o.t format,
will reliably output codon-format function calls instead of JSON.
"""

import sys, os, re, json, time, statistics
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_QUERIES = [
    ("What is the weather in Beijing for the next 7 days?", "@1.1.0"),
    ("I need a 3-day forecast for Tokyo.", "@1.1.0"),
    ("What is the current temperature in London right now?", "@1.2.0"),
    ("Are there any severe weather alerts in Asia?", "@2.1.0"),
    ("Get me the weather forecast for Singapore for the next 14 days.", "@1.1.0"),
    ("Show me the weather at coordinates 35.7 latitude, 139.7 longitude for 5 days.", "@1.1.1"),
    ("What is the weather like in Paris today?", "@1.1.0 | @1.2.0"),
    ("Any alerts for North America?", "@2.1.0"),
    ("Tell me the temperature in Dubai.", "@1.2.0"),
    ("Give me a 1-day forecast for Berlin.", "@1.1.0"),
    ("What is the weather forecast for Mumbai with 7 days' outlook?", "@1.1.0"),
    ("Current conditions in Moscow.", "@1.2.0"),
    ("Are there weather warnings for Europe?", "@2.1.0"),
    ("Cairo weather for the next 5 days.", "@1.1.0"),
    ("Temperature check for Seoul right now.", "@1.2.0"),
    ("What alerts are active in Lagos?", "@2.1.0"),
    ("7-day weather outlook for Toronto.", "@1.1.0"),
    ("What is the weather at 40.7N, 74.0W for 3 days?", "@1.1.1"),
    ("Lima forecast for 7 days.", "@1.1.0"),
    ("Current weather in Bangkok.", "@1.2.0"),
]

SYSTEM_PROMPT = """You are a weather assistant that MUST use a specific function-calling format.

To call a function, output a single line in this EXACT format:
@service.operation.template param1 param2 ...

Available functions:
  @1.1.0 <city> <days>    — get weather forecast (e.g. @1.1.0 Beijing 7)
  @1.1.1 <lat> <lon> <days> — get forecast by coordinates (e.g. @1.1.1 35.7 139.7 5)
  @1.2.0 <city>            — get current weather (e.g. @1.2.0 London)
  @2.1.0 <region> <severity> — get weather alerts (e.g. @2.1.0 Asia severe)

RULES:
- Output ONLY the @ line. No explanation, no markdown, no JSON.
- String parameters do NOT need quotes.
- Numbers are plain digits.
- Separate parameters with spaces.
- If the user asks for "forecast" or "weather for N days", use @1.1.0.
- If they ask for "current" or "temperature" or "now", use @1.2.0.
- If they ask for "alerts" or "warnings", use @2.1.0.
- If days is not specified, default to 7.
- If severity is not specified, use "severe"."""

# ─── Simulated mode ────────────────────────────────────────────────

CITY_MAP = {
    'beijing': 'Beijing', 'tokyo': 'Tokyo', 'london': 'London',
    'paris': 'Paris', 'dubai': 'Dubai', 'berlin': 'Berlin',
    'mumbai': 'Mumbai', 'moscow': 'Moscow', 'cairo': 'Cairo',
    'seoul': 'Seoul', 'lagos': 'Lagos', 'toronto': 'Toronto',
    'lima': 'Lima', 'bangkok': 'Bangkok', 'singapore': 'Singapore',
}

def simulate_llm(query, expected):
    """Simulate what a well-trained LLM should output."""
    q = query.lower()
    # Extract city
    city = 'Beijing'
    for cname, cproper in CITY_MAP.items():
        if cname in q:
            city = cproper
            break
    # Extract days
    days_match = re.search(r'(\d+)[\s-]*day', q)
    days = int(days_match.group(1)) if days_match else 7
    # Detect intent
    if 'alert' in q or 'warning' in q or 'warn' in q:
        region = city if city not in ('Beijing', 'Tokyo') else 'Asia'
        sev = 'severe'
        return f'@2.1.0 {region} {sev}', expected
    if 'current' in q or 'temperature' in q or 'now' in q or 'today' in q and 'forecast' not in q:
        return f'@1.2.0 {city}', expected
    if re.search(r'[\d.]+\s*[NSns].*[\d.]+\s*[EWew]', q) or 'coordinate' in q or 'lat' in q:
        coords = re.findall(r'([\d.]+)', q)
        lat = coords[0] if len(coords) > 0 else '35.7'
        lon = coords[1] if len(coords) > 1 else '139.7'
        return f'@1.1.1 {lat} {lon} {days}', expected
    return f'@1.1.0 {city} {days}', expected

def check_compliance(output, expected_prefix):
    """Check if output matches @s.o.t format."""
    match = re.match(r'@(\d+)\.(\d+)\.(\d+)\s+.+', output.strip())
    if not match:
        return False, "no @s.o.t match", output[:60]
    actual_prefix = f'@{match.group(1)}.{match.group(2)}.{match.group(3)}'
    # Check if it's one of the valid codons
    valid = {'@1.1.0', '@1.1.1', '@1.2.0', '@2.1.0'}
    if actual_prefix not in valid:
        return False, f'invalid codon {actual_prefix}', output[:60]
    # Semantic check: was the right kind of operation chosen?
    ok = (actual_prefix == expected_prefix or
          (expected_prefix == '@1.1.0 | @1.2.0' and actual_prefix in ('@1.1.0', '@1.2.0')))
    return ok, 'correct' if ok else f'expected {expected_prefix}', output[:60]

# ─── Real LLM mode ─────────────────────────────────────────────────

def real_llm_test(api_key):
    """Test with actual Claude API."""
    import urllib.request

    results = {'correct': 0, 'wrong_format': 0, 'wrong_codon': 0, 'total': 0}
    details = []
    latencies = []

    for query, expected in TEST_QUERIES:
        t0 = time.perf_counter()
        try:
            body = json.dumps({
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 50,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": query}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
            output = resp['content'][0]['text']
            latencies.append((time.perf_counter() - t0) * 1000)

            ok, reason, preview = check_compliance(output, expected)
            results['total'] += 1
            if ok:
                results['correct'] += 1
            elif 'format' in reason or 'no @' in reason:
                results['wrong_format'] += 1
            else:
                results['wrong_codon'] += 1
            details.append((query[:50], output[:60], reason, ok))
        except Exception as e:
            details.append((query[:50], f'ERROR: {e}', 'api_error', False))
            results['total'] += 1

    return results, details, latencies

# ─── Main ──────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--simulate':
        mode = 'simulate'
    elif len(sys.argv) > 1:
        mode = 'real'
        api_key = sys.argv[1]
    else:
        print("Usage: python3 relay/llm_test.py <ANTHROPIC_API_KEY>")
        print("   or: python3 relay/llm_test.py --simulate")
        print()
        print("No API key provided. Running SIMULATION mode...")
        mode = 'simulate'

    if mode == 'simulate':
        print("╔══════════════════════════════════════════════════════════╗")
        print("║   LLM @s.o.t Compliance Test — SIMULATED                ║")
        print("║   (Run with API key for real LLM results)               ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print()
        print(f"{'Query':<45} {'Output':<35} {'Verdict'}")
        print("-" * 95)

        correct = 0
        for query, expected in TEST_QUERIES:
            output, exp = simulate_llm(query, expected)
            ok, reason, preview = check_compliance(output, exp)
            if ok: correct += 1
            mark = '✅' if ok else '❌'
            print(f"{query[:43]:<45} {output[:33]:<35} {mark} {reason}")

        print("-" * 95)
        total = len(TEST_QUERIES)
        print(f"Compliance: {correct}/{total} ({correct/total*100:.0f}%)")
        print()
        print("NOTE: This is simulated. A real LLM may do slightly worse due to")
        print("occasional formatting errors. Run with an API key to test real behavior:")
        print("  python3 relay/llm_test.py YOUR_ANTHROPIC_API_KEY")
        print()
        return

    # Real LLM test
    print(f"Testing {len(TEST_QUERIES)} queries with Claude API...")
    results, details, latencies = real_llm_test(api_key)

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   LLM @s.o.t Compliance Test — REAL CLAUDE API          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(f"{'Query':<45} {'Output':<35} {'Verdict'}")
    print("-" * 95)
    for query, output, reason, ok in details:
        mark = '✅' if ok else '❌'
        print(f"{query[:43]:<45} {output[:33]:<35} {mark} {reason}")
    print("-" * 95)

    total = results['total']
    print(f"Results: {total} queries")
    print(f"  Correct format:     {results['correct']} ({results['correct']/total*100:.0f}%)")
    print(f"  Wrong format:       {results['wrong_format']}")
    print(f"  Wrong codon chosen: {results['wrong_codon']}")
    if latencies:
        print(f"  Avg latency:        {statistics.mean(latencies):.0f}ms")
    print()

    if results['correct'] / max(total, 1) > 0.8:
        print("VERDICT: LLM reliably outputs @s.o.t format (>80% compliance).")
        print("The relay gateway approach is viable.")
    elif results['correct'] / max(total, 1) > 0.5:
        print("VERDICT: Mixed. @s.o.t works but needs fallback handling.")
        print("Consider: retry on format error, or fine-tune system prompt.")
    else:
        print("VERDICT: Low compliance. @s.o.t format may need model fine-tuning.")
        print("Consider: adding few-shot examples to system prompt.")

if __name__ == '__main__':
    main()
