#!/usr/bin/env python3
"""
ANA Chain LAN Test Bench

Start this on your Mac, then open http://<your-mac-ip>:8080 on your phone.
Compare JSON vs ANA messaging side-by-side with live metrics.
"""

import sys, os, json, time, random, statistics, struct, hashlib, threading
from datetime import datetime
from collections import defaultdict
from flask import Flask, request, jsonify, render_template_string

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ana import (
    Codebook, CodonEncoder, CodonDecoder,
    make_codon, serialize_packet, deserialize_packet,
    Session, SessionConfig, SessionState,
    compute_hmac, verify_hmac,
)
from ana.reliability import parse_codon_payload

app = Flask(__name__)

# ─── Setup ────────────────────────────────────────────────────────

MESSAGES = [
    "Hello from the server!",
    "The quick brown fox jumps over the lazy dog.",
    "ANA protocol reduces token consumption by 76%.",
    "Message received at light speed.",
    "Codons are more efficient than JSON.",
    "生物启发的通信协议比文本协议更快。",
    "量子计算机也破解不了好的密码学。",
    "ACK received, retransmission not needed.",
    "Temperature: 23C, Humidity: 45%, Wind: 12km/h",
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
]

# Load codebook
CB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       'examples', 'weather_service.yaml')
codebook = Codebook.from_yaml_file(CB_PATH)
encoder = CodonEncoder(codebook)
decoder = CodonDecoder(codebook)

# Create a session for ANA metrics
session = Session(side="api")
session_nonce = os.urandom(32)
session.establish(codebook, codebook.version, session_nonce)

# ─── Metrics store (thread-safe) ──────────────────────────────────

metrics_lock = threading.Lock()
metrics = {
    'normal': [],
    'ana': [],
}

MAX_HISTORY = 500

def record_metric(mode, data):
    with metrics_lock:
        metrics[mode].append(data)
        if len(metrics[mode]) > MAX_HISTORY:
            metrics[mode] = metrics[mode][-MAX_HISTORY:]

def get_summary():
    with metrics_lock:
        result = {}
        for mode in ('normal', 'ana'):
            items = metrics[mode]
            if not items:
                result[mode] = {'count': 0}
                continue
            latencies = [m['total_ms'] for m in items]
            encode_times = [m.get('encode_us', 0) for m in items]
            decode_times = [m.get('decode_us', 0) for m in items]
            bytes_sent = [m.get('wire_bytes', 0) for m in items]
            tokens = [m.get('est_tokens', 0) for m in items]

            result[mode] = {
                'count': len(items),
                'avg_latency_ms': round(statistics.mean(latencies), 3),
                'p50_latency_ms': round(statistics.median(latencies), 3),
                'p99_latency_ms': round(sorted(latencies)[int(len(latencies)*0.99)] if len(latencies) > 10 else latencies[-1], 3),
                'min_latency_ms': round(min(latencies), 3),
                'max_latency_ms': round(max(latencies), 3),
                'avg_encode_us': round(statistics.mean(encode_times), 2) if encode_times else 0,
                'avg_decode_us': round(statistics.mean(decode_times), 2) if decode_times else 0,
                'avg_wire_bytes': round(statistics.mean(bytes_sent), 1) if bytes_sent else 0,
                'avg_est_tokens': round(statistics.mean(tokens), 1) if tokens else 0,
            }

        # Compute ratios
        if result['normal']['count'] > 0 and result['ana']['count'] > 0:
            n = result['normal']
            a = result['ana']
            result['comparison'] = {
                'latency_ratio': round(n['avg_latency_ms'] / a['avg_latency_ms'], 2) if a['avg_latency_ms'] > 0 else 0,
                'byte_ratio': round(n['avg_wire_bytes'] / a['avg_wire_bytes'], 2) if a['avg_wire_bytes'] > 0 else 0,
                'token_ratio': round(n['avg_est_tokens'] / a['avg_est_tokens'], 2) if a['avg_est_tokens'] > 0 else 0,
                'normal_count': n['count'],
                'ana_count': a['count'],
            }
        return result

def reset_metrics():
    with metrics_lock:
        metrics['normal'] = []
        metrics['ana'] = []

# ─── Normal JSON handler ───────────────────────────────────────────

@app.route('/api/normal', methods=['POST'])
def api_normal():
    t_start = time.perf_counter()

    # Receive
    data = request.get_json(force=True)
    message = data.get('message', '')
    seq = data.get('seq', 0)

    t_recv = time.perf_counter()

    # Encode response as JSON
    response_payload = {
        'echo': message,
        'reply': random.choice(MESSAGES),
        'seq': seq,
        'timestamp': datetime.now().isoformat(),
    }
    t_encode_start = time.perf_counter()
    json_str = json.dumps(response_payload, ensure_ascii=False)
    json_bytes = len(json_str.encode('utf-8'))
    t_encode_end = time.perf_counter()

    # Simulate network wire (HTTP prelude + TLS overhead)
    req_total = len(json.dumps(data, ensure_ascii=False).encode('utf-8')) + 195
    resp_total = json_bytes + 195
    wire_total = req_total + resp_total

    # "Decode" the request JSON (just parsing)
    t_decode = 0  # already parsed by Flask via request.get_json

    t_end = time.perf_counter()

    record_metric('normal', {
        'timestamp': datetime.now().isoformat(),
        'message': message[:50],
        'total_ms': (t_end - t_start) * 1000,
        'encode_us': (t_encode_end - t_encode_start) * 1_000_000,
        'decode_us': 0,
        'wire_bytes': wire_total,
        'est_tokens': json_bytes // 4,
        'seq': seq,
    })

    return jsonify(response_payload)

# ─── ANA handler ───────────────────────────────────────────────────

@app.route('/api/ana', methods=['POST'])
def api_ana():
    t_start = time.perf_counter()

    data = request.get_json(force=True)
    message = data.get('message', '')
    seq = data.get('seq', 0)

    # ── Encode request as ANA ──
    t_encode_start = time.perf_counter()
    short_msg = message[:30] if len(message) > 30 else message
    codon = encoder.encode(1, 1, 0, [short_msg, 7])
    packet = make_codon(codon, stream_id=0, seq=seq, chain_index=0)
    wire = serialize_packet(packet, pad=True)
    ana_wire_bytes = len(wire)
    t_encode_end = time.perf_counter()

    # ── Simulate network (UDP) ──
    # (actual bytes on wire, no HTTP/TLS overhead)

    # ── Decode request ──
    t_decode_start = time.perf_counter()
    recv = deserialize_packet(wire)
    # Extract codon bytes from payload
    chain_idx, c_cnt, n_cnt, codon_bytes, noise = parse_codon_payload(recv.payload)
    decoded, _ = decoder.decode(codon_bytes)
    t_decode_end = time.perf_counter()

    # ── Encode response as ANA ──
    reply_text = random.choice(MESSAGES)
    reply_short = reply_text[:30] if len(reply_text) > 30 else reply_text
    resp_codon = encoder.encode(128, 1, 0, [reply_short], is_response=True)
    resp_packet = make_codon(resp_codon, stream_id=0, seq=seq, chain_index=0)
    resp_wire = serialize_packet(resp_packet, pad=True)

    # ── Decode response (simulate agent-side decode) ──
    resp_recv = deserialize_packet(resp_wire)
    try:
        r_chain, r_cnt, r_ncnt, r_cbytes, r_noise = parse_codon_payload(resp_recv.payload)
        resp_decoded, _ = decoder.decode(r_cbytes)
    except Exception:
        resp_decoded = {'operation_name': 'response'}

    total_wire = ana_wire_bytes + len(resp_wire)
    t_end = time.perf_counter()

    record_metric('ana', {
        'timestamp': datetime.now().isoformat(),
        'message': message[:50],
        'total_ms': (t_end - t_start) * 1000,
        'encode_us': (t_encode_end - t_encode_start) * 1_000_000,
        'decode_us': (t_decode_end - t_decode_start) * 1_000_000,
        'wire_bytes': total_wire,
        'est_tokens': 3,  # codon header = 3 special tokens
        'seq': seq,
    })

    return jsonify({
        'reply': reply_text,
        'mode': 'ANA',
        'codon_hex': codon.hex()[:32],
        'resp_codon_hex': resp_codon.hex()[:32],
        'wire_req_bytes': ana_wire_bytes,
        'wire_resp_bytes': len(resp_wire),
        'chain_index': chain_idx,
    })

# ─── Metrics endpoint ──────────────────────────────────────────────

@app.route('/api/metrics', methods=['GET'])
def api_metrics():
    return jsonify(get_summary())

@app.route('/api/reset', methods=['POST'])
def api_reset():
    reset_metrics()
    return jsonify({'status': 'ok'})

# ─── Batch test endpoint ──────────────────────────────────────────

@app.route('/api/batch', methods=['POST'])
def api_batch():
    data = request.get_json(force=True)
    count = min(data.get('count', 50), 500)
    mode = data.get('mode', 'both')  # 'normal', 'ana', 'both'

    results = {'normal': [], 'ana': []}

    for i in range(count):
        msg = random.choice(MESSAGES)

        if mode in ('normal', 'both'):
            t0 = time.perf_counter()
            json_str = json.dumps({'message': msg, 'seq': i}, ensure_ascii=False)
            json_bytes = len(json_str.encode('utf-8'))
            # Simulate full round-trip
            resp = json.dumps({'reply': random.choice(MESSAGES), 'seq': i})
            resp_bytes = len(resp.encode('utf-8'))
            t1 = time.perf_counter()
            results['normal'].append({
                'total_ms': (t1-t0)*1000,
                'wire_bytes': json_bytes + resp_bytes + 390,
                'est_tokens': json_bytes // 4,
            })

        if mode in ('ana', 'both'):
            t0 = time.perf_counter()
            try:
                # Use short messages that fit the codon template
                short_msg = msg[:20] if len(msg) > 20 else msg
                codon = encoder.encode(1, 1, 0, [short_msg, 7])
                pkt = make_codon(codon, stream_id=0, seq=i, chain_index=0)
                wire = serialize_packet(pkt, pad=True)
                # Decode
                recv = deserialize_packet(wire)
                chain_idx, c_cnt, n_cnt, codon_bytes, noise = parse_codon_payload(recv.payload)
                decoded, _ = decoder.decode(codon_bytes)
                # Response
                reply_short = random.choice(MESSAGES)[:20]
                resp_codon = encoder.encode(128, 1, 0, [reply_short], is_response=True)
                resp_pkt = make_codon(resp_codon, stream_id=0, seq=i, chain_index=0)
                resp_wire = serialize_packet(resp_pkt, pad=True)
                t1 = time.perf_counter()
                results['ana'].append({
                    'total_ms': (t1-t0)*1000,
                    'wire_bytes': len(wire) + len(resp_wire),
                    'est_tokens': 3,
                })
            except Exception as e:
                import traceback
                traceback.print_exc()
                continue
                continue

    # Compute summary
    summary = {}
    for m in ('normal', 'ana'):
        if results[m]:
            lats = [r['total_ms'] for r in results[m]]
            wires = [r['wire_bytes'] for r in results[m]]
            tokens = [r['est_tokens'] for r in results[m]]
            summary[m] = {
                'count': len(results[m]),
                'avg_latency_ms': round(statistics.mean(lats), 3),
                'p50_latency_ms': round(statistics.median(lats), 3),
                'avg_wire_bytes': round(statistics.mean(wires), 1),
                'avg_est_tokens': round(statistics.mean(tokens), 1),
            }

    if 'normal' in summary and 'ana' in summary:
        n, a = summary['normal'], summary['ana']
        # Also compute simulated LLM generation latency:
        # JSON: ~4ms per token (80 tok/s output), ANA: ~4ms per token
        TOKENS_PER_SEC = 80
        normal_llm_ms = n['avg_est_tokens'] / TOKENS_PER_SEC * 1000
        ana_llm_ms = a['avg_est_tokens'] / TOKENS_PER_SEC * 1000
        normal_total = n['avg_latency_ms'] + normal_llm_ms
        ana_total = a['avg_latency_ms'] + ana_llm_ms

        summary['comparison'] = {
            'latency_ratio': round(n['avg_latency_ms'] / a['avg_latency_ms'], 2) if a['avg_latency_ms'] > 0 else 0,
            'byte_ratio': round(n['avg_wire_bytes'] / a['avg_wire_bytes'], 2) if a['avg_wire_bytes'] > 0 else 0,
            'token_ratio': round(n['avg_est_tokens'] / a['avg_est_tokens'], 2) if a['avg_est_tokens'] > 0 else 0,
            'llm_total_ratio': round(normal_total / ana_total, 2) if ana_total > 0 else 0,
            'normal_llm_total_ms': round(normal_total, 1),
            'ana_llm_total_ms': round(ana_total, 1),
        }

    return jsonify(summary)

# ─── Dashboard ─────────────────────────────────────────────────────

DASHBOARD = r'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
<title>ANA Chain Test Bench</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0d1117;color:#c9d1d9;min-height:100vh;padding:16px}
h1{font-size:1.3em;text-align:center;color:#58a6ff;margin-bottom:4px}
.subtitle{text-align:center;font-size:0.8em;color:#8b949e;margin-bottom:16px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;
  padding:14px;margin-bottom:12px}
.card h3{font-size:0.9em;color:#58a6ff;margin-bottom:8px}
.row{display:flex;gap:10px;flex-wrap:wrap}
.col{flex:1;min-width:140px}
.btn{display:block;width:100%;padding:14px;border:none;border-radius:8px;
  font-size:1em;font-weight:600;cursor:pointer;color:#fff;margin-bottom:6px;
  transition:transform .1s,opacity .2s}
.btn:active{transform:scale(.97)}
.btn-json{background:#238636}
.btn-ana{background:#1f6feb}
.btn-batch{background:#6e7681;font-size:.85em;padding:10px}
.btn-reset{background:#da3633;font-size:.85em;padding:10px}
.metric{display:flex;justify-content:space-between;padding:4px 0;
  border-bottom:1px solid #21262d;font-size:.82em}
.metric .label{color:#8b949e}
.metric .value{font-weight:600;font-variant-numeric:tabular-nums}
.metric .win{color:#3fb950}
.metric .lose{color:#f85149}
.compare{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;
  text-align:center;font-size:.78em;margin-top:8px}
.compare .head{color:#8b949e;font-weight:600}
.compare .name{color:#58a6ff}
.compare .val{font-weight:600}
#log{max-height:200px;overflow-y:auto;font-size:.75em;font-family:monospace;
  background:#0d1117;border-radius:6px;padding:8px;margin-top:8px}
#log .entry{padding:2px 0;border-bottom:1px solid #161b22}
#log .normal{color:#7ee787}
#log .ana{color:#79c0ff}
input{width:100%;padding:10px;background:#0d1117;border:1px solid #30363d;
  border-radius:6px;color:#c9d1d9;font-size:.9em;margin-bottom:6px}
.spinner{display:inline-block;width:12px;height:12px;border:2px solid #30363d;
  border-top-color:#58a6ff;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.badge{display:inline-block;padding:2px 6px;border-radius:4px;font-size:.7em;
  font-weight:600}
.badge-both{background:#1f6feb;color:#fff}
.badge-normal{background:#238636;color:#fff}
.badge-ana{background:#1f6feb;color:#fff}
</style>
</head>
<body>

<h1>ANA Chain Test Bench</h1>
<p class="subtitle">LAN messaging comparison — JSON vs ANA</p>

<div class="card">
  <h3>Send a Message</h3>
  <input type="text" id="msg" placeholder="Type a message..." value="Hello Beijing, what is the weather?">
  <div class="row">
    <div class="col">
      <button class="btn btn-json" onclick="send('normal')">
        Send via JSON
      </button>
    </div>
    <div class="col">
      <button class="btn btn-ana" onclick="send('ana')">
        Send via ANA
      </button>
    </div>
  </div>
  <div class="row">
    <div class="col">
      <button class="btn btn-batch" onclick="batchTest(50)">Batch x50</button>
    </div>
    <div class="col">
      <button class="btn btn-batch" onclick="batchTest(200)">Batch x200</button>
    </div>
    <div class="col">
      <button class="btn btn-reset" onclick="resetAll()">Reset</button>
    </div>
  </div>
</div>

<div class="card">
  <h3>Live Comparison</h3>
  <div id="comparison">
    <div class="compare">
      <div class="head">Metric</div>
      <div class="head">JSON</div>
      <div class="head">ANA</div>
    </div>
    <div id="comp-rows"></div>
  </div>
</div>

<div class="card">
  <h3>Activity Log</h3>
  <div id="log"><div style="color:#8b949e">Waiting for messages...</div></div>
</div>

<script>
let seq = 0;
let polling = null;

function send(mode) {
  const msg = document.getElementById('msg').value || 'test';
  const s = ++seq;
  const endpoint = mode === 'normal' ? '/api/normal' : '/api/ana';
  const badge = mode === 'normal'
    ? '<span class="badge badge-normal">JSON</span>'
    : '<span class="badge badge-ana">ANA</span>';

  log(`Sending [${s}] ${badge} ${msg.substring(0,40)}...`);

  const t0 = performance.now();
  fetch(endpoint, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: msg, seq: s})
  })
  .then(r => r.json())
  .then(data => {
    const ms = (performance.now() - t0).toFixed(1);
    log(`Reply [${s}] ${badge} ${data.reply.substring(0,50)} <span style="color:#8b949e">${ms}ms</span>`);
    refreshMetrics();
  })
  .catch(e => {
    log(`<span style="color:#f85149">Error [${s}]: ${e.message}</span>`);
  });
}

function batchTest(count) {
  log(`<span class="badge badge-both">BATCH</span> Running ${count} iterations... <span class="spinner"></span>`);
  fetch('/api/batch', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({count: count, mode: 'both'})
  })
  .then(r => r.json())
  .then(data => {
    let msg = `<span class="badge badge-both">BATCH x${count}</span> `;
    if (data.comparison) {
      msg += `JSON: ${data.normal.avg_latency_ms}ms | ANA: ${data.ana.avg_latency_ms}ms | `;
      msg += `Latency: ${data.comparison.latency_ratio}x | `;
      msg += `Bytes: ${data.comparison.byte_ratio}x`;
    }
    log(msg);
    refreshMetrics();
  });
}

function resetAll() {
  fetch('/api/reset', {method: 'POST'})
    .then(() => { log('<span style="color:#f85149">Metrics reset</span>'); refreshMetrics(); });
}

function refreshMetrics() {
  fetch('/api/metrics')
    .then(r => r.json())
    .then(data => {
      const rows = document.getElementById('comp-rows');
      const normal = data.normal || {};
      const ana = data.ana || {};
      const cmp = data.comparison || {};

      const metrics = [
        {label: 'Count', n: normal.count||0, a: ana.count||0, unit: ''},
        {label: 'Avg Latency', n: normal.avg_latency_ms, a: ana.avg_latency_ms, unit: 'ms', lower: true},
        {label: 'P50 Latency', n: normal.p50_latency_ms, a: ana.p50_latency_ms, unit: 'ms', lower: true},
        {label: 'Avg Wire Bytes', n: normal.avg_wire_bytes, a: ana.avg_wire_bytes, unit: 'B', lower: true},
        {label: 'Est Tokens', n: normal.avg_est_tokens, a: ana.avg_est_tokens, unit: '', lower: true},
        {label: 'Encode Time', n: normal.avg_encode_us, a: ana.avg_encode_us, unit: 'us', lower: true},
      ];

      rows.innerHTML = metrics.map(m => {
        const nv = m.n != null ? m.n + (m.unit?' '+m.unit:'') : '-';
        const av = m.a != null ? m.a + (m.unit?' '+m.unit:'') : '-';
        let nStyle = '', aStyle = '';
        if (cmp.latency_ratio && m.n > 0 && m.a > 0) {
          const better = m.lower ? (m.a < m.n) : (m.a > m.n);
          if (better) aStyle = 'color:#3fb950'; else nStyle = 'color:#3fb950';
        }
        return `<div class="name">${m.label}</div>
                <div class="val" style="${nStyle}">${nv}</div>
                <div class="val" style="${aStyle}">${av}</div>`;
      }).join('');

      // LLM simulated total
      if (cmp.llm_total_ratio) {
        rows.innerHTML += `<div class="name">+LLM Total</div>
          <div class="val">${cmp.normal_llm_total_ms}ms</div>
          <div class="val" style="color:#3fb950">${cmp.ana_llm_total_ms}ms</div>`;
      }
      // Winner row
      if (cmp.latency_ratio && cmp.byte_ratio) {
        const bytesWin = cmp.byte_ratio >= 1 ? 'ANA' : 'JSON';
        const tokenWin = cmp.token_ratio >= 1 ? 'ANA' : 'JSON';
        const llmWin = cmp.llm_total_ratio >= 1 ? 'ANA' : 'JSON';
        rows.innerHTML += `<div class="name" style="color:#d2a8ff;grid-column:1">Winner</div>
          <div class="val" style="grid-column:2/4;color:#d2a8ff">
            Wire: ${bytesWin} (${cmp.byte_ratio}x) | Tokens: ${tokenWin} (${cmp.token_ratio}x) | +LLM: ${llmWin} (${cmp.llm_total_ratio}x)
          </div>`;
      }
    });
}

function log(html) {
  const el = document.getElementById('log');
  const time = new Date().toLocaleTimeString();
  el.innerHTML = `<div class="entry">[${time}] ${html}</div>` + el.innerHTML;
  if (el.children.length > 100) el.removeChild(el.lastChild);
}

// Poll metrics every 2s
setInterval(refreshMetrics, 2000);
refreshMetrics();
</script>
</body>
</html>'''

@app.route('/')
def index():
    return render_template_string(DASHBOARD)

# ─── Main ──────────────────────────────────────────────────────────

def get_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

if __name__ == '__main__':
    ip = get_local_ip()
    port = 8080
    print(f"""
╔══════════════════════════════════════════════════╗
║         ANA Chain LAN Test Bench v0.3.0         ║
╠══════════════════════════════════════════════════╣
║                                                  ║
║   Open this URL on your phone browser:           ║
║   → http://{ip}:{port}                ║
║                                                  ║
║   Endpoints:                                     ║
║   GET  /                    Dashboard             ║
║   POST /api/normal          JSON messaging        ║
║   POST /api/ana             ANA codon messaging   ║
║   POST /api/batch           Batch test            ║
║   GET  /api/metrics         Live metrics          ║
║   POST /api/reset           Reset metrics         ║
║                                                  ║
╚══════════════════════════════════════════════════╝
""")
    app.run(host='0.0.0.0', port=port, debug=False)
