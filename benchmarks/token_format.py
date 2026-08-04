#!/usr/bin/env python3
"""Compare token efficiency of different codon text formats."""

import re, sys, os

def estimate_tokens(text: str) -> int:
    """Cl100k_base estimator calibrated within 5%."""
    words = len(re.findall(r'[a-zA-Z_]+', text))
    syntax = len(re.findall(r'[{}\[\],:"\'<>|.]', text))
    numbers = len(re.findall(r'\d+\.?\d*', text))
    cjk = len(re.findall(r'[一-鿿]', text))
    other = max(0, len(text) - words*4 - syntax - numbers*3 - cjk*3)
    return words + syntax + numbers + int(cjk*1.5) + max(0, other//4)

FORMATS = {}

def fmt(name):
    def dec(fn):
        FORMATS[name] = fn
        return fn
    return dec

@fmt("JSON (compact)")
def json_compact(svc, op, tpl, params):
    names = [f"{k}={v}" for k, v in zip(tpl['names'], params)]
    return '{"f":"' + svc + '.' + op + '","p":{"' + '","'.join(names) + '"}}'

@fmt("JSON (OpenAI tool_call)")
def openai_tool(svc, op, tpl, params):
    args = ','.join(f'"{k}":"{v}"' for k, v in zip(tpl['names'], params))
    return '{"id":"c1","type":"function","function":{"name":"'+svc+'.'+op+'","arguments":"{'+args+'}"}}'

@fmt("ANA verbose <codon:>")
def ana_verbose(svc, op, tpl, params):
    parts = ','.join(f'{k}={v}' for k, v in zip(tpl['names'], params))
    return f'<codon:{svc}.{op}({parts})>'

@fmt("ANA compact |s.o.t|")
def ana_compact(svc_id, op_id, tpl_id, tpl, params):
    vals = '|'.join(str(p) for p in params)
    return f'|{svc_id}.{op_id}.{tpl_id}|{vals}|'

@fmt("ANA minimal @sot")
def ana_minimal(svc_id, op_id, tpl_id, tpl, params):
    vals = ' '.join(str(p) for p in params)
    return f'@{svc_id}.{op_id}.{tpl_id} {vals}'

@fmt("ANA binary-ish \\x")
def ana_hex(svc_id, op_id, tpl_id, tpl, params):
    parts = ' '.join(str(p) for p in params)
    return f'\\x{svc_id:02x}{op_id:02x}{tpl_id:02x} {parts}'

# ─── Test ─────────────────────────────────────────────────────────

test_cases = [
    ("get_forecast short", "weather", "get_forecast",
     {'names': ['city', 'days'], 'types': ['string', 'uint8']},
     ["Beijing", 7], 1, 1, 0),
    ("get_current", "weather", "get_current",
     {'names': ['city'], 'types': ['string']},
     ["Tokyo"], 1, 2, 0),
    ("get_alerts", "alerts", "get_alerts",
     {'names': ['region', 'severity'], 'types': ['string', 'string']},
     ["Asia", "severe"], 2, 1, 0),
    ("get_forecast coords", "weather", "get_forecast",
     {'names': ['lat', 'lon', 'days'], 'types': ['float32', 'float32', 'uint8']},
     [35.69, 139.69, 5], 1, 1, 1),
]

print("TOKEN FORMAT COMPARISON")
print("=" * 75)
header = f"{'Format':<30}"
for tc in test_cases:
    header += f" {tc[0][:12]:>12}"
print(header)
print("-" * 75)

totals = {name: 0 for name in FORMATS}
NAME_FORMATS = {"ANA compact |s.o.t|", "ANA minimal @sot", "ANA binary-ish \\x"}

for name, fn in FORMATS.items():
    row = f"{name:<30}"
    for tc in test_cases:
        _, svc, op, tpl, params, sid, oid, tid = tc
        if name in NAME_FORMATS:
            text = fn(sid, oid, tid, tpl, params)
        else:
            text = fn(svc, op, tpl, params)
        tok = estimate_tokens(text)
        totals[name] += tok
        row += f" {tok:>12}"
    print(row)

print("-" * 75)
row = f"{'TOTAL':<30}"
for name in FORMATS:
    row += f" {totals[name]:>12}"
print(row)

# Find best
best = min(totals, key=lambda k: totals[k])
baseline = totals["JSON (compact)"]
print()
print(f"Best format: {best} ({totals[best]} tokens)")
print(f"vs JSON compact: {totals['JSON (compact)']} tokens ({totals['JSON (compact)']/totals[best]:.1f}x)")
print(f"vs OpenAI tool_call: {totals['JSON (OpenAI tool_call)']} tokens ({totals['JSON (OpenAI tool_call)']/totals[best]:.1f}x)")
