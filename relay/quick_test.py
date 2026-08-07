#!/usr/bin/env python3
"""
ANA Relay — Quick Test (zero setup, no server needed)

Run:  python3 relay/quick_test.py

Compares JSON relay vs ANA codon relay side-by-side.
All in-memory — no Flask, no network, just the ANA library.

Perfect for: first-time evaluation, CI benchmarks, demos.
"""

import sys, os, time, re, json, random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ana import Codebook, CodonEncoder, CodonDecoder

CB = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                  'examples', 'weather_service.yaml')
codebook = Codebook.from_yaml_file(CB)
encoder = CodonEncoder(codebook)
decoder = CodonDecoder(codebook)

# ─── Token estimator ───────────────────────────────────────────────

def est_tokens(text: str) -> int:
    words = len(re.findall(r'[a-zA-Z_]+', text))
    syntax = len(re.findall(r'[{}\[\],:"\'<>|.@]', text))
    numbers = len(re.findall(r'\d+\.?\d*', text))
    cjk = len(re.findall(r'[一-鿿]', text))
    other = max(0, len(text) - words*4 - syntax - numbers*3 - cjk*3)
    return words + syntax + numbers + int(cjk*1.5) + max(0, other//4)

# ─── Test cases ────────────────────────────────────────────────────

CASES = [
    ("@1.1.0 Beijing 7",        "get_forecast by city"),
    ("@1.1.0 Tokyo 3",          "get_forecast short"),
    ("@1.2.0 London",           "get_current"),
    ("@2.1.0 Asia severe",      "get_alerts"),
    ("@1.1.1 35.7 139.7 5",    "get_forecast by coords"),
]

# ─── JSON equivalent ───────────────────────────────────────────────

def json_relay_format(svc_id, op_id, tpl_id, params):
    svc = codebook.get_service(svc_id)
    op = codebook.get_operation(svc_id, op_id)
    tpl = codebook.get_template(svc_id, op_id, tpl_id)
    p = dict(zip(tpl.params, params))
    # OpenAI tool_call format
    return json.dumps({
        "id": "call_abc123", "type": "function",
        "function": {
            "name": f"{svc.name}.{op.name}",
            "arguments": json.dumps(p)
        }
    }, ensure_ascii=False)

def codon_relay_format(svc_id, op_id, tpl_id, params):
    parts = ' '.join(str(p) for p in params)
    return f'@{svc_id}.{op_id}.{tpl_id} {parts}'

# ─── Simulate relay call ──────────────────────────────────────────

def sim_json_relay(codon_text):
    svc, op, tpl, params = _parse(codon_text)
    jr = json_relay_format(svc, op, tpl, params)
    resp = json.dumps({'result': _mock_api(svc, op, tpl, params)},
                      ensure_ascii=False)
    return len(jr) + len(resp) + 390, est_tokens(jr) + est_tokens(resp)

def sim_codon_relay(codon_text):
    svc, op, tpl, params = _parse(codon_text)
    cr = codon_relay_format(svc, op, tpl, params)
    resp = _mock_api(svc, op, tpl, params)
    return len(cr), est_tokens(cr) + 3

def _parse(text):
    m = re.match(r'@(\d+)\.(\d+)\.(\d+)\s+(.+)', text.strip())
    svc, op, tpl = int(m.group(1)), int(m.group(2)), int(m.group(3))
    parts = m.group(4).strip().split()
    template = codebook.get_template(svc, op, tpl)
    params = []
    for i, (p, typ) in enumerate(zip(parts, template.types)):
        if typ == 'uint8': params.append(int(p))
        elif typ == 'float32': params.append(float(p))
        else: params.append(p)
    return svc, op, tpl, params

def _mock_api(svc, op, tpl, params):
    if svc == 1 and op == 1:
        return {'city': params[0], 'forecast': [{'day':1,'high':22,'low':12,'cond':'Sunny'}]}
    if svc == 1 and op == 2:
        return {'city': params[0], 'temp': 22, 'condition': 'Clear'}
    return {'ok': True}

# ─── Run ───────────────────────────────────────────────────────────

def main():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        ANA RELAY — Quick Test (zero setup)                  ║")
    print("║        Compares JSON relay vs ANA codon relay               ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    total_j_bytes, total_c_bytes = 0, 0
    total_j_tok, total_c_tok = 0, 0

    print(f"{'Call':<30} {'JSON bytes':>10} {'Codon bytes':>12} {'JSON tok':>8} {'Codon tok':>9} {'Tok save':>8}")
    print("-" * 80)

    for codon_text, desc in CASES:
        jb, jt = sim_json_relay(codon_text)
        cb, ct = sim_codon_relay(codon_text)
        total_j_bytes += jb; total_c_bytes += cb
        total_j_tok += jt; total_c_tok += ct
        save = (1 - ct/jt)*100 if jt > 0 else 0
        print(f"{desc:<30} {jb:>10} {cb:>12} {jt:>8} {ct:>9} {save:>7.0f}%")

    print("-" * 80)
    print(f"{'TOTAL':<30} {total_j_bytes:>10} {total_c_bytes:>12} {total_j_tok:>8} {total_c_tok:>9} {(1-total_c_tok/total_j_tok)*100:>7.0f}%")
    print()

    # Per-call averages
    n = len(CASES)
    print("PER-CALL AVERAGES:")
    print(f"  JSON relay:  {total_j_bytes//n} bytes, {total_j_tok//n} tokens")
    print(f"  Codon relay: {total_c_bytes//n} bytes, {total_c_tok//n} tokens")
    print(f"  Token ratio: {total_j_tok/total_c_tok:.1f}x")
    print(f"  Byte ratio:  {total_j_bytes/total_c_bytes:.1f}x")
    print()

    # Cost model
    DAILY = 10_000
    PRICE = 15.0
    json_cost = total_j_tok / n * DAILY * 30 / 1_000_000 * PRICE
    codon_cost = total_c_tok / n * DAILY * 30 / 1_000_000 * PRICE
    print(f"COST MODEL ({DAILY:,} calls/day, ${PRICE}/M tokens):")
    print(f"  JSON relay monthly:  ${json_cost:.2f}")
    print(f"  Codon relay monthly: ${codon_cost:.2f}")
    print(f"  Annual savings:      ${(json_cost - codon_cost) * 12:.2f}")
    print()

    # Individual examples
    print("WHAT THE LLM SEES:")
    for codon_text, desc in CASES[:3]:
        svc, op, tpl, params = _parse(codon_text)
        jr = json_relay_format(svc, op, tpl, params)
        cr = codon_relay_format(svc, op, tpl, params)
        print(f"\n  {desc}:")
        print(f"    JSON:  {jr[:80]}...")
        print(f"           ({est_tokens(jr)} tokens)")
        print(f"    Codon: {cr}")
        print(f"           ({est_tokens(cr)} tokens)")

    print()
    print("─" * 80)
    print("To test with the full relay server: python3 relay/server.py")
    print("Then open http://<your-ip>:6060 on your phone or browser.")
    print("─" * 80)
    print()

if __name__ == '__main__':
    main()
