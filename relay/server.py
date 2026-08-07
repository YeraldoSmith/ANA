"""
ANA Relay — API Gateway with ANA codon-based dispatch.

Start:  python3 relay/server.py
Open:   http://<ip>:6060

A relay/gateway that:
1. Publishes a codebook so any LLM Agent can discover available APIs
2. Accepts @s.o.t codon-format function calls (no JSON parser needed)
3. Forwards to downstream APIs via integer table lookup
4. Returns codon-format responses (minimal token overhead)

This is the "中转站" pattern: the relay becomes the codebook authority.
LLMs only need to output @1.1.0 Beijing 7 — 6 tokens instead of 62.
"""

import sys, os, json, time, random, re, struct
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ana import (
    Codebook, CodonEncoder, CodonDecoder,
    make_codon, serialize_packet, deserialize_packet,
    Session, SessionConfig,
)
from ana.reliability import parse_codon_payload
from relay.token_counter import count, label as token_label

app = Flask(__name__)

# ─── Load codebook ─────────────────────────────────────────────────

CB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       'examples', 'weather_service.yaml')
codebook = Codebook.from_yaml_file(CB_PATH)
encoder = CodonEncoder(codebook)
decoder = CodonDecoder(codebook)

# Stats
stats = {'codon_calls': 0, 'json_calls': 0, 'total_codon_tokens': 0,
         'total_json_tokens': 0, 'started': datetime.now().isoformat()}

# ─── Codebook registry endpoint ────────────────────────────────────

@app.route('/v1/codebook', methods=['GET'])
def get_codebook():
    """Publish the codebook so any LLM can discover available APIs."""
    services = []
    for svc in codebook.services.values():
        ops = []
        for op in svc.operations:
            tmps = []
            for t in op.templates:
                tmps.append({
                    'id': t.id,
                    'description': t.description,
                    'params': t.params,
                    'types': t.types,
                    'defaults': t.defaults,
                    'codon': f'@{svc.id}.{op.id}.{t.id}',
                    'example': f'@{svc.id}.{op.id}.{t.id} ' +
                        ' '.join(str(t.defaults.get(p, f'<{p}>'))
                                 for p in t.params),
                })
            ops.append({'id': op.id, 'name': op.name, 'templates': tmps})
        services.append({'id': svc.id, 'name': svc.name, 'operations': ops})

    prompt_hint = (
        "When calling functions, use the format: @service.operation.template param1 param2 ...\n"
        "Parameters are space-separated, strings do not need quotes.\n"
        "Example: @1.1.0 Beijing 7 means get_forecast(city=Beijing, days=7)."
    )

    return jsonify({
        'codebook_id': codebook.version.codebook_id,
        'version': codebook.version.version,
        'services': services,
        'system_prompt_hint': prompt_hint,
    })

# ─── Traditional JSON relay endpoint ───────────────────────────────

@app.route('/v1/json/chat', methods=['POST'])
def json_relay():
    """Traditional relay: JSON in → parse → forward → JSON out."""
    t0 = time.perf_counter()
    data = request.get_json(force=True)
    message = data.get('message', '').strip()
    mode = data.get('mode', 'auto')

    # Parse intent from message (simple NLU)
    svc_id, op_id, tpl_id, params = _parse_message(message, mode)
    tpl = codebook.get_template(svc_id, op_id, tpl_id)
    param_dict = dict(zip(tpl.params, params))

    # Forward to downstream API
    result = _call_downstream(svc_id, op_id, tpl_id, params)

    # Format response as JSON
    json_resp = json.dumps({
        'service': codebook.get_service(svc_id).name,
        'operation': codebook.get_operation(svc_id, op_id).name,
        'parameters': param_dict,
        'result': result,
    }, ensure_ascii=False)

    stats['json_calls'] += 1
    stats['total_json_tokens'] += len(json_resp) // 4

    # Token count: call-side JSON + response data (both measured with same counter)
    call_tok = count(json.dumps(data, ensure_ascii=False))
    resp_tok = count(json_resp)

    return jsonify({
        'mode': 'json',
        'result': result,
        'call_tokens': call_tok,
        'resp_tokens': resp_tok,
        'total_tokens': call_tok + resp_tok,
        'token_label': token_label(),
        'latency_ms': round((time.perf_counter() - t0) * 1000, 3),
    })

# ─── ANA codon relay endpoint ──────────────────────────────────────

@app.route('/v1/codon/chat', methods=['POST'])
def codon_relay():
    """ANA relay: @s.o.t format in → table lookup → forward → codon out."""
    t0 = time.perf_counter()
    data = request.get_json(force=True)
    message = data.get('message', '').strip()

    # Parse @s.o.t format: @1.1.0 Beijing 7
    svc_id, op_id, tpl_id, params = _parse_codon_format(message)

    # Table lookup
    svc = codebook.get_service(svc_id)
    op = codebook.get_operation(svc_id, op_id)
    tpl = codebook.get_template(svc_id, op_id, tpl_id)

    # Forward to downstream API
    result = _call_downstream(svc_id, op_id, tpl_id, params)

    # Encode response as ANA
    codon = encoder.encode(128, 1, 0, [json.dumps(result, ensure_ascii=False)],
                           is_response=True)
    pkt = make_codon(codon, chain_index=0)
    wire = serialize_packet(pkt, pad=True)

    stats['codon_calls'] += 1
    stats['total_codon_tokens'] += 6  # @s.o.t params format

    # Token count: codon format (call-side) + same response data
    codon_text = f'@{svc_id}.{op_id}.{tpl_id} ' + ' '.join(str(p) for p in params)
    call_tok = count(codon_text)
    resp_tok = count(json.dumps(result, ensure_ascii=False))

    return jsonify({
        'mode': 'codon',
        'codon': f'@{svc_id}.{op_id}.{tpl_id}',
        'operation': f'{svc.name}.{op.name}',
        'params': dict(zip(tpl.params, params)),
        'result': result,
        'wire_bytes': len(wire),
        'call_tokens': call_tok,
        'resp_tokens': resp_tok,
        'total_tokens': call_tok + resp_tok,
        'token_label': token_label(),
        'latency_ms': round((time.perf_counter() - t0) * 1000, 3),
    })

# ─── Comparison endpoint ───────────────────────────────────────────

@app.route('/v1/compare', methods=['POST'])
def compare():
    """Run both JSON and codon relay on the same request, compare."""
    data = request.get_json(force=True)
    message = data.get('message', '').strip()
    count = min(data.get('iterations', 50), 200)

    json_times = []
    codon_times = []
    json_tokens = 0
    codon_tokens = 0

    for _ in range(count):
        # JSON path
        t0 = time.perf_counter()
        svc, op, tpl, params = _parse_message(message, 'auto')
        result = _call_downstream(svc, op, tpl, params)
        jr = json.dumps({'service': codebook.get_service(svc).name,
                         'operation': codebook.get_operation(svc, op).name,
                         'result': result}, ensure_ascii=False)
        json_times.append(time.perf_counter() - t0)
        json_tokens += len(jr) // 4

        # Codon path
        t0 = time.perf_counter()
        svc, op, tpl, params = _parse_codon_format(message)
        result = _call_downstream(svc, op, tpl, params)
        codon_times.append(time.perf_counter() - t0)
        codon_tokens += 6

    import statistics
    return jsonify({
        'iterations': count,
        'json': {
            'avg_ms': round(statistics.mean(json_times) * 1000, 4),
            'total_tokens': json_tokens,
            'tokens_per_call': round(json_tokens / count, 1),
        },
        'codon': {
            'avg_ms': round(statistics.mean(codon_times) * 1000, 4),
            'total_tokens': codon_tokens,
            'tokens_per_call': round(codon_tokens / count, 1),
        },
        'comparison': {
            'speedup': round(statistics.mean(json_times) / max(statistics.mean(codon_times), 1e-9), 2),
            'token_reduction': round((1 - codon_tokens / json_tokens) * 100, 1) if json_tokens > 0 else 0,
            'token_ratio': round(json_tokens / codon_tokens, 1) if codon_tokens > 0 else 0,
        },
    })

# ─── Stats endpoint ────────────────────────────────────────────────

@app.route('/v1/stats', methods=['GET'])
def get_stats():
    total = stats['codon_calls'] + stats['json_calls']
    return jsonify({
        **stats,
        'total_calls': total,
        'uptime_seconds': (datetime.now() - datetime.fromisoformat(stats['started'])).total_seconds(),
    })

# ─── Helpers ───────────────────────────────────────────────────────

def _parse_codon_format(text: str):
    """Parse @s.o.t format: @1.1.0 Beijing 7 → (1, 1, 0, ['Beijing', 7])."""
    m = re.match(r'@(\d+)\.(\d+)\.(\d+)\s+(.+)', text.strip())
    if m:
        svc, op, tpl = int(m.group(1)), int(m.group(2)), int(m.group(3))
        params_str = m.group(4).strip()
        # Split by spaces, convert numbers
        parts = params_str.split()
        template = codebook.get_template(svc, op, tpl)
        params = []
        for i, (p, typ) in enumerate(zip(parts, template.types)):
            if typ == 'uint8':
                params.append(int(p))
            elif typ in ('float32',):
                params.append(float(p))
            else:
                params.append(p)
        return svc, op, tpl, params
    # Fallback: try natural language
    return _parse_message(text, 'auto')

def _parse_message(text, mode):
    """Simple NLU: map natural language to codebook operations."""
    text = text.lower().strip()
    if 'current' in text or 'temp' in text or 'now' in text or '温度' in text or '现在' in text:
        city = re.sub(r'(current|temp|temperature|now|温度|现在|in|at|for|\?)', '', text, flags=re.IGNORECASE).strip() or 'Beijing'
        return 1, 2, 0, [city]
    if 'alert' in text or '警报' in text or '预警' in text:
        region = re.sub(r'(alert|alerts|warning|警报|预警|in|for|\?)', '', text, flags=re.IGNORECASE).strip() or 'Asia'
        return 2, 1, 0, [region, 'severe']
    # Default: forecast
    days_match = re.search(r'(\d+)\s*(day|天)', text)
    days = int(days_match.group(1)) if days_match else 7
    city = re.sub(r'(weather|forecast|天气|预报|\?|what|is|the|in|for|告诉我|查询)', '', text, flags=re.IGNORECASE).strip()
    city = city.replace(str(days), '').replace('day', '').replace('天', '').strip() or 'Beijing'
    return 1, 1, 0, [city, days]

def _call_downstream(svc_id, op_id, tpl_id, params):
    """Simulate a downstream API call."""
    if svc_id == 1 and op_id == 1:
        city, days = params[0], params[1] if len(params) > 1 else 7
        return {'city': city, 'days': days,
                'forecast': [{'day': i+1, 'high': 20+i, 'low': 10+i,
                              'condition': random.choice(['Sunny','Cloudy','Rain'])}
                             for i in range(min(days, 7))]}
    elif svc_id == 1 and op_id == 2:
        return {'city': params[0], 'temp': 22, 'humidity': 65, 'condition': 'Clear'}
    elif svc_id == 2 and op_id == 1:
        return {'region': params[0], 'alerts': ['Wind advisory'] if len(params) > 1 else []}
    return {'error': 'unknown'}

# ─── Dashboard ─────────────────────────────────────────────────────

DASH = r'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>ANA Relay</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0d1117;
  color:#c9d1d9;padding:12px}
h1{font-size:1.2em;color:#58a6ff;text-align:center}
.sub{text-align:center;font-size:.75em;color:#8b949e;margin-bottom:12px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;
  padding:12px;margin-bottom:10px}
.card h3{font-size:.85em;color:#58a6ff;margin-bottom:6px}
input,button{padding:10px;border-radius:6px;font-size:.9em}
input{flex:1;background:#0d1117;border:1px solid #30363d;color:#c9d1d9}
button{background:#1f6feb;border:none;color:#fff;font-weight:600;cursor:pointer}
.btn2{background:#238636}.btn3{background:#6e7681}
.row{display:flex;gap:6px;margin-bottom:4px}
pre{background:#0d1117;border-radius:4px;padding:8px;font-size:.7em;
  overflow-x:auto;max-height:200px;overflow-y:auto}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:.75em}
.met{background:#0d1117;padding:8px;border-radius:4px;text-align:center}
.met .val{font-size:1.3em;font-weight:700}.met .lbl{color:#8b949e;font-size:.7em}
.win{color:#3fb950}.lose{color:#f85149}
</style></head><body>
<h1>ANA Relay</h1><p class="sub">API Gateway — @s.o.t codon dispatch</p>
<div class="metrics" id="metrics">
  <div class="met"><div class="val" id="m-codon">0</div><div class="lbl">Codon Calls</div></div>
  <div class="met"><div class="val" id="m-json">0</div><div class="lbl">JSON Calls</div></div>
  <div class="met"><div class="val win" id="m-ratio">-</div><div class="lbl">Token Ratio</div></div>
  <div class="met"><div class="val" id="m-uptime">0s</div><div class="lbl">Uptime</div></div>
</div>
<div class="card"><h3>Test Call</h3>
  <div class="row"><input id="msg" value="@1.1.0 Beijing 7" onkeydown="if(event.key==='Enter')call('codon')">
    <button onclick="call('codon')">@ Codon</button>
    <button class="btn2" onclick="call('json')">JSON</button></div>
  <div class="row">
    <button class="btn3" onclick="compare()">Compare x50</button>
    <button class="btn3" onclick="loadCodebook()">Load Codebook</button>
    <button class="btn3" onclick="loadStats()">Stats</button>
  </div>
  <pre id="out">Send a @s.o.t codon or natural language message...</pre>
</div>
<script>
async function call(mode){
  const msg=document.getElementById('msg').value;
  const ep=mode==='codon'?'/v1/codon/chat':'/v1/json/chat';
  const r=await fetch(ep,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message:msg})});
  const d=await r.json();
  document.getElementById('out').textContent=JSON.stringify(d,null,2);
  loadStats();
}
async function compare(){
  const msg=document.getElementById('msg').value;
  document.getElementById('out').textContent='Running 50 iterations...';
  const r=await fetch('/v1/compare',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({message:msg,iterations:50})});
  const d=await r.json();
  document.getElementById('out').textContent=JSON.stringify(d,null,2);
}
async function loadCodebook(){
  const r=await fetch('/v1/codebook');const d=await r.json();
  document.getElementById('out').textContent=JSON.stringify(d,null,2);
}
async function loadStats(){
  const r=await fetch('/v1/stats');const d=await r.json();
  document.getElementById('m-codon').textContent=d.codon_calls;
  document.getElementById('m-json').textContent=d.json_calls;
  if(d.codon_calls&&d.json_calls){
    const cr=d.total_codon_tokens/Math.max(1,d.codon_calls);
    const jr=d.total_json_tokens/Math.max(1,d.json_calls);
    document.getElementById('m-ratio').textContent=(jr/cr).toFixed(1)+'x';
  }
  document.getElementById('m-uptime').textContent=Math.round(d.uptime_seconds)+'s';
}
loadStats();setInterval(loadStats,3000);
</script></body></html>'''

@app.route('/')
def index():
    return render_template_string(DASH)

# ─── Main ──────────────────────────────────────────────────────────

def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(('8.8.8.8', 80)); return s.getsockname()[0]
    except: return '127.0.0.1'
    finally: s.close()

if __name__ == '__main__':
    ip = get_ip()
    print(f"""
╔══════════════════════════════════════════════════╗
║         ANA Relay — API Gateway                  ║
╠══════════════════════════════════════════════════╣
║  Dashboard: http://{ip}:6060            ║
║  Codebook:  http://{ip}:6060/v1/codebook         ║
║  Codon API: POST /v1/codon/chat                  ║
║  JSON API:  POST /v1/json/chat                   ║
║  Compare:   POST /v1/compare                     ║
╚══════════════════════════════════════════════════╝
""")
    app.run(host='0.0.0.0', port=6060, debug=False)
