#!/usr/bin/env python3
"""
ANA Agent — Minimal ANA-compatible Agent for protocol testing.

Start:  python3 agent/server.py
Open:   http://<your-ip>:5050

A simulated AI Agent that understands natural language, maps it to
ANA codons, and demonstrates the full protocol pipeline.
"""

import sys, os, json, time, random, re, struct
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ana import (
    Codebook, CodonEncoder, CodonDecoder,
    make_codon, serialize_packet, deserialize_packet,
)
from ana.reliability import parse_codon_payload

app = Flask(__name__)

# ─── Setup ────────────────────────────────────────────────────────

CB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       'examples', 'weather_service.yaml')
codebook = Codebook.from_yaml_file(CB_PATH)
encoder = CodonEncoder(codebook)
decoder = CodonDecoder(codebook)

# ─── NLU — Simple intent parser (no LLM needed) ──────────────────

INTENTS = [
    # (regex, service_id, op_id, tpl_id, param_extractor_fn)
    (r"(?:weather|forecast|天气|天|预报).*?(?:in|at|for)?\s*([A-Za-zÀ-ÿ一-鿿\s]+?)(?:\s+(\d+)\s*(?:day|天|日))?$",
     1, 1, 0, lambda m: [m.group(1).strip(), int(m.group(2) or 7)]),
    (r"(?:weather|forecast|天气).*?(\d+)\s*(?:day|天|日)",
     1, 1, 0, lambda m: ["Beijing", int(m.group(1))]),
    (r"(?:current|now|temp|temperature|现在|温度|当前).*?(?:in|at|for)?\s*(.+)",
     1, 2, 0, lambda m: [m.group(1).strip()]),
    (r"(?:alert|warning|警报|预警).*?(?:in|for)?\s*(.+)",
     2, 1, 0, lambda m: [m.group(1).strip(), "severe"]),
    (r"(?:forecast|weather).*?([\d.]+)\s*,\s*([\d.]+)",
     1, 1, 1, lambda m: [float(m.group(1)), float(m.group(2)), 3]),
]

def parse_intent(text):
    """Parse natural language into a codebook operation call."""
    text = text.strip()
    for pattern, svc, op, tpl, extractor in INTENTS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return svc, op, tpl, extractor(m)
    # Default: treat as a city name for forecast
    return 1, 1, 0, [text[:30], 7]

# ─── Mock weather API ────────────────────────────────────────────

def mock_api_call(service_id, op_id, tpl_id, params):
    """Simulate a weather API response."""
    if service_id == 1 and op_id == 1:  # get_forecast
        city = params[0] if len(params) > 0 else "Unknown"
        days = params[1] if len(params) > 1 else 7
        conditions = ["Sunny", "Cloudy", "Rain", "Clear", "Overcast", "Windy", "Fog"]
        forecast = [{"day": i+1, "high": 18+random.randint(0,15),
                     "low": 5+random.randint(0,10),
                     "condition": random.choice(conditions)}
                    for i in range(min(days, 14))]
        return {"city": city, "days": days, "forecast": forecast}
    elif service_id == 1 and op_id == 2:  # get_current
        city = params[0] if params else "Unknown"
        return {"city": city, "temp": 15+random.randint(0,20),
                "humidity": 40+random.randint(0,50),
                "condition": random.choice(["Sunny","Cloudy","Rain","Clear"])}
    elif service_id == 2 and op_id == 1:  # get_alerts
        region = params[0] if params else "Unknown"
        return {"region": region, "alerts": ["Thunderstorm watch", "Wind advisory"][:random.randint(0,2)]}
    return {"error": "Unknown operation"}

# ─── API endpoint for Agent ──────────────────────────────────────

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json(force=True)
    user_text = data.get('message', '').strip()
    if not user_text:
        return jsonify({'error': 'empty message'})

    steps = []
    t_total_start = time.perf_counter()

    # ── Step 1: NLU parsing ──
    t0 = time.perf_counter()
    svc, op, tpl, params = parse_intent(user_text)
    svc_def = codebook.get_service(svc)
    op_def = codebook.get_operation(svc, op)
    tpl_def = codebook.get_template(svc, op, tpl)
    param_dict = dict(zip(tpl_def.params, params))
    steps.append({
        'step': 1, 'name': 'NLU Parsing',
        'detail': f'Intent: {svc_def.name}.{op_def.name}({param_dict})',
        'time_us': round((time.perf_counter()-t0)*1e6, 1),
    })

    # ── Step 2: ANA codon encode ──
    t0 = time.perf_counter()
    codon_bytes = encoder.encode(svc, op, tpl, params)
    pkt = make_codon(codon_bytes, stream_id=0, seq=0, chain_index=0)
    wire = serialize_packet(pkt, pad=True)
    ana_encode_us = round((time.perf_counter()-t0)*1e6, 1)
    steps.append({
        'step': 2, 'name': 'ANA Codon Encoding',
        'detail': f'Codon: {codon_bytes.hex()} ({len(codon_bytes)}B), Packet: {len(wire)}B wire',
        'time_us': ana_encode_us,
    })

    # ── Step 3: ANA transport (simulated) ──
    steps.append({
        'step': 3, 'name': 'ANA Transport',
        'detail': f'UDP send → receive ({len(wire)}B, padded, CRC-16)',
        'time_us': 0,
    })

    # ── Step 4: ANA decode ──
    t0 = time.perf_counter()
    recv = deserialize_packet(wire)
    chain, cnt, ncnt, cbytes, noise = parse_codon_payload(recv.payload)
    decoded, _ = decoder.decode(cbytes)
    ana_decode_us = round((time.perf_counter()-t0)*1e6, 1)
    steps.append({
        'step': 4, 'name': 'ANA Anticodon Lookup',
        'detail': f'Decoded: {decoded["service_name"]}.{decoded["operation_name"]}({decoded["params"]})',
        'time_us': ana_decode_us,
    })

    # ── Step 5: API call ──
    t0 = time.perf_counter()
    api_result = mock_api_call(svc, op, tpl, params)
    api_us = round((time.perf_counter()-t0)*1e6, 1)
    steps.append({
        'step': 5, 'name': 'API Execution',
        'detail': f'Result: {json.dumps(api_result, ensure_ascii=False)[:100]}...',
        'time_us': api_us,
    })

    # ── Step 6: ANA response encode ──
    t0 = time.perf_counter()
    result_json = json.dumps(api_result, ensure_ascii=False)
    resp_codon = encoder.encode(128, 1, 0, [result_json], is_response=True)
    resp_pkt = make_codon(resp_codon, stream_id=0, seq=0, chain_index=0)
    resp_wire = serialize_packet(resp_pkt, pad=True)
    resp_encode_us = round((time.perf_counter()-t0)*1e6, 1)
    steps.append({
        'step': 6, 'name': 'ANA Response Encode',
        'detail': f'Response codon: {resp_codon.hex()[:30]}... ({len(resp_wire)}B wire)',
        'time_us': resp_encode_us,
    })

    # ── Step 7: ANA response decode ──
    t0 = time.perf_counter()
    resp_recv = deserialize_packet(resp_wire)
    r_chain, r_cnt, r_ncnt, r_cbytes, r_noise = parse_codon_payload(resp_recv.payload)
    resp_decoded, _ = decoder.decode(r_cbytes)
    resp_decode_us = round((time.perf_counter()-t0)*1e6, 1)
    steps.append({
        'step': 7, 'name': 'ANA Response Decode',
        'detail': f'Decoded response ({len(result_json)} chars of data)',
        'time_us': resp_decode_us,
    })

    # ── JSON equivalent for comparison ──
    json_req = json.dumps({'function': f'{svc_def.name}.{op_def.name}',
                           'parameters': param_dict}, ensure_ascii=False)
    json_resp = json.dumps(api_result, ensure_ascii=False)
    json_wire = len(json_req) + len(json_resp) + 390  # +HTTP/TLS overhead

    ana_total_wire = len(wire) + len(resp_wire)
    ana_total_time = ana_encode_us + ana_decode_us + resp_encode_us + resp_decode_us + api_us

    total_ms = round((time.perf_counter()-t_total_start)*1000, 3)

    return jsonify({
        'intent': f'{svc_def.name}.{op_def.name}',
        'params': param_dict,
        'result': api_result,
        'ana': {
            'total_wire_bytes': ana_total_wire,
            'total_time_us': round(ana_total_time, 1),
            'req_bytes': len(wire),
            'resp_bytes': len(resp_wire),
            'codon_hex': codon_bytes.hex()[:40],
        },
        'json_equiv': {
            'total_wire_bytes': json_wire,
            'req_len': len(json_req),
            'resp_len': len(json_resp),
        },
        'comparison': {
            'byte_reduction': round((1 - ana_total_wire/json_wire)*100, 1),
            'bytes_ratio': round(json_wire/ana_total_wire, 1),
        },
        'total_ms': total_ms,
        'steps': steps,
    })

# ─── Dashboard ────────────────────────────────────────────────────

DASH = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,user-scalable=no">
<title>ANA Agent</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0d1117;color:#c9d1d9;min-height:100vh;padding:12px}
h1{font-size:1.1em;color:#58a6ff;text-align:center;margin-bottom:2px}
.sub{text-align:center;font-size:.75em;color:#8b949e;margin-bottom:10px}
.chat{display:flex;flex-direction:column;gap:8px;margin-bottom:10px;
  max-height:55vh;overflow-y:auto}
.msg{padding:10px 12px;border-radius:8px;font-size:.85em;line-height:1.4;
  animation:fadeIn .2s}
.msg.user{background:#1f6feb22;border:1px solid #1f6feb44;align-self:flex-end;
  max-width:85%}
.msg.agent{background:#23863622;border:1px solid #23863644;align-self:flex-start;
  max-width:92%}
.msg .header{font-size:.7em;color:#8b949e;margin-bottom:4px}
.msg .content{word-break:break-word}
.steps{margin-top:6px;padding:6px 8px;background:#0d1117;border-radius:4px;
  font-size:.7em;font-family:monospace}
.step{display:flex;justify-content:space-between;padding:2px 0;
  border-bottom:1px solid #161b22}
.step .name{color:#58a6ff}
.step .time{color:#8b949e}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:.75em}
.metric{background:#161b22;border:1px solid #30363d;border-radius:6px;
  padding:8px;text-align:center}
.metric .val{font-size:1.3em;font-weight:700}
.metric .label{color:#8b949e;font-size:.75em}
.metric .win{color:#3fb950}
.metric .lose{color:#f85149}
.input-row{display:flex;gap:6px}
input{flex:1;padding:10px;background:#0d1117;border:1px solid #30363d;
  border-radius:8px;color:#c9d1d9;font-size:.9em}
button{padding:10px 18px;background:#1f6feb;border:none;border-radius:8px;
  color:#fff;font-weight:600;cursor:pointer;font-size:.9em}
button:active{transform:scale(.97)}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
.badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:.65em}
.b-ana{background:#1f6feb44;color:#79c0ff}
.b-json{background:#23863644;color:#7ee787}
.spin{display:inline-block;width:10px;height:10px;border:2px solid #30363d;
  border-top-color:#58a6ff;border-radius:50%;animation:spin .6s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<h1>ANA Agent</h1>
<p class="sub">Minimal ANA-Compatible Agent — Protocol Test Harness</p>

<div class="metrics" id="metrics">
  <div class="metric"><div class="val" id="m-count">0</div><div class="label">Messages</div></div>
  <div class="metric"><div class="val" id="m-bytes">-</div><div class="label">ANA Wire Bytes</div></div>
  <div class="metric"><div class="val win" id="m-reduction">-</div><div class="label">Byte Reduction vs JSON</div></div>
  <div class="metric"><div class="val" id="m-latency">-</div><div class="label">Total Latency</div></div>
</div>

<div class="chat" id="chat"></div>

<div class="input-row">
  <input id="input" placeholder="Ask about weather... e.g. 'What is the weather in Tokyo?'"
         onkeydown="if(event.key==='Enter')send()">
  <button onclick="send()">Send</button>
</div>

<script>
let count = 0, totalBytes = 0, totalJsonBytes = 0, totalLatency = 0;

function send() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  count++;

  const chat = document.getElementById('chat');
  chat.innerHTML += `<div class="msg user"><div class="header">You</div>
    <div class="content">${esc(text)}</div></div>`;

  const agentDiv = document.createElement('div');
  agentDiv.className = 'msg agent';
  agentDiv.innerHTML = `<div class="header">ANA Agent <span class="spin"></span></div>
    <div class="content">Processing...</div>`;
  chat.appendChild(agentDiv);
  chat.scrollTop = chat.scrollHeight;

  const t0 = performance.now();
  fetch('/api/chat', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({message:text})
  })
  .then(r => r.json())
  .then(data => {
    const latency = (performance.now()-t0).toFixed(1);
    totalLatency += parseFloat(latency);
    totalBytes += data.ana.total_wire_bytes;
    totalJsonBytes += data.json_equiv.total_wire_bytes;

    // Build steps HTML
    let stepsHtml = '';
    if (data.steps) {
      stepsHtml = '<div class="steps">';
      data.steps.forEach(s => {
        stepsHtml += `<div class="step"><span class="name">${s.step}. ${s.name}</span>
          <span class="time">${s.time_us}us</span></div>`;
        stepsHtml += `<div style="color:#8b949e;font-size:.9em;padding-left:12px">${esc(s.detail)}</div>`;
      });
      stepsHtml += '</div>';
    }

    const forecast = data.result.forecast;
    let resultHtml = '';
    if (forecast) {
      resultHtml = `<b>${data.result.city}</b> ${data.result.days}-day forecast:<br>`;
      forecast.forEach(f => {
        resultHtml += `Day ${f.day}: ${f.condition} ${f.high}C/${f.low}C<br>`;
      });
    } else if (data.result.temp != null) {
      resultHtml = `<b>${data.result.city}</b>: ${data.result.temp}C, ${data.result.condition}`;
    } else if (data.result.alerts) {
      resultHtml = `<b>${data.result.region}</b>: ${data.result.alerts.join(', ') || 'No alerts'}`;
    } else {
      resultHtml = JSON.stringify(data.result).substring(0,200);
    }

    const cmp = data.comparison;
    agentDiv.innerHTML = `<div class="header">ANA Agent <span class="badge b-ana">ANA</span>
      ${latency}ms |
      <span class="badge b-json">JSON equiv</span> ${cmp.bytes_ratio}x larger</div>
      <div class="content">${resultHtml}</div>
      <div style="font-size:.7em;color:#8b949e;margin-top:4px">
      Intent: ${data.intent}(${JSON.stringify(data.params)}) |
      ANA: ${data.ana.total_wire_bytes}B | JSON: ${data.json_equiv.total_wire_bytes}B |
      Reduction: ${cmp.byte_reduction}%
      </div>
      ${stepsHtml}`;

    chat.scrollTop = chat.scrollHeight;

    // Update metrics
    document.getElementById('m-count').textContent = count;
    document.getElementById('m-bytes').textContent = Math.round(totalBytes/count) + 'B avg';
    document.getElementById('m-reduction').textContent =
      Math.round((1 - totalBytes/totalJsonBytes)*100) + '%';
    document.getElementById('m-latency').textContent =
      Math.round(totalLatency/count) + 'ms avg';
  })
  .catch(e => {
    agentDiv.innerHTML = `<div class="header">ANA Agent <span style="color:#f85149">Error</span></div>
      <div class="content">${esc(e.message)}</div>`;
  });
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
</script>
</body>
</html>'''

@app.route('/')
def index():
    return render_template_string(DASH)

# ─── Main ──────────────────────────────────────────────────────────

def get_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

if __name__ == '__main__':
    ip = get_ip()
    port = 5050
    print(f"""
╔══════════════════════════════════════════════════╗
║           ANA Agent — Protocol Tester            ║
╠══════════════════════════════════════════════════╣
║  Open: http://{ip}:{port}            ║
║                                                  ║
║  Try: "weather in Tokyo"                         ║
║       "current temp in London"                   ║
║       "alerts in Asia"                           ║
║       "forecast for 35.7, 139.7"                 ║
║       "Beijing 3 day forecast"                   ║
╚══════════════════════════════════════════════════╝
""")
    app.run(host='0.0.0.0', port=port, debug=False)
