#!/usr/bin/env python3
"""
API-side demo of the ANA Chain protocol.

Simulates a weather API server that receives codon-based
requests and sends codon-based responses.
"""

import socket
import time
import sys
import os
import json
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ana import (
    Codebook, CodonEncoder, CodonDecoder,
    Packet, PacketType, serialize_packet, deserialize_packet,
    Session, SessionState,
    Negotiator,
)
from ana.transport import UDPReceiver
from ana.packet import make_codon, make_error, ErrorCode


class WeatherAPI:
    """Simulated weather API backend."""

    @staticmethod
    def get_forecast(city: str, days: int) -> dict:
        return {
            "city": city,
            "days": days,
            "forecast": [{"day": i+1, "high": 20+i, "low": 10+i,
                          "condition": "sunny" if i % 2 == 0 else "cloudy"}
                         for i in range(days)]
        }

    @staticmethod
    def get_current(city: str) -> dict:
        return {"city": city, "temp": 22, "humidity": 65,
                "condition": "partly cloudy", "wind": "15 km/h"}

    @staticmethod
    def get_alerts(region: str, severity: str) -> dict:
        alerts = {"all": ["thunderstorm watch", "heat advisory"],
                  "severe": ["thunderstorm watch"]}
        return {"region": region, "alerts": alerts.get(severity, [])}


def demo_api_handling():
    """Demonstrate the API-side handling of codon requests."""
    print("ANA Chain Protocol — API Demo")
    print()

    # Load codebook
    yaml_path = os.path.join(os.path.dirname(__file__), 'weather_service.yaml')
    codebook = Codebook.from_yaml_file(yaml_path)

    # Simulate receiving codons and dispatching
    encoder = CodonEncoder(codebook)
    decoder = CodonDecoder(codebook)
    api = WeatherAPI()

    print("=" * 60)
    print("INCOMING REQUESTS (simulated)")
    print("=" * 60)

    # Simulated incoming requests
    requests = [
        (1, 1, 0, ["Beijing", 7]),      # get_forecast by city
        (1, 2, 0, ["Tokyo"]),           # get_current
        (2, 1, 0, ["Asia", "severe"]),  # get_alerts
        (1, 1, 1, [35.7, 139.7, 3]),   # get_forecast by coordinates
        (99, 1, 0, []),                  # unknown service (triggers error)
    ]

    for svc_id, op_id, tpl_id, params in requests:
        try:
            # Encode as if received from agent
            codon_bytes = encoder.encode(svc_id, op_id, tpl_id, params)
            print(f"\n  Received codon: {codon_bytes.hex()}")

            # Decode
            decoded, _ = decoder.decode(codon_bytes)

            if decoded.get('is_noise'):
                print(f"    → NOISE, discarded")
                continue
            if decoded.get('is_reserved'):
                print(f"    → RESERVED, forward to extension handler")
                continue

            print(f"    → {decoded['service_name']}.{decoded['operation_name']}"
                  f"({decoded['params']})")

            # Dispatch to handler
            svc_name = decoded['service_name']
            op_name = decoded['operation_name']
            p = decoded['params']

            if svc_name == 'weather' and op_name == 'get_forecast':
                if 'city' in p:
                    result = api.get_forecast(p['city'], p.get('days', 7))
                else:
                    result = api.get_forecast(f"({p['lat']},{p['lon']})", p.get('days', 3))
            elif svc_name == 'weather' and op_name == 'get_current':
                result = api.get_current(p['city'])
            elif svc_name == 'alerts' and op_name == 'get_alerts':
                result = api.get_alerts(p['region'], p.get('severity', 'all'))
            else:
                result = {"error": f"Unknown operation: {svc_name}.{op_name}"}

            # Encode response (using the system service, op=1 = response_success)
            result_json = json.dumps(result, ensure_ascii=False)
            response_codon = encoder.encode(
                128, 1, 0,
                [result_json],
                is_response=True
            )
            print(f"    ← Response codon ({len(response_codon)}B): {response_codon.hex()[:40]}...")

            # Decode response on agent side (simulation)
            resp_decoded, _ = decoder.decode(response_codon)
            print(f"    ← Response: {resp_decoded['operation_name']}"
                  f" ({len(resp_decoded.get('params', {}).get('message', ''))} chars)")
            print(f"       is_response flag: {resp_decoded['is_response']}")

        except KeyError as e:
            print(f"    → ERROR: {e}")
            print(f"    → Would send ERROR packet with code CODON_UNKNOWN")
            # In real protocol: send_error(ErrorCode.CODON_UNKNOWN, str(e))

    # Performance summary
    print()
    print("=" * 60)
    print("PERFORMANCE SUMMARY")
    print("=" * 60)

    # One round-trip comparison
    print("\n  Single get_forecast(city='London', days=5):")
    codon = encoder.encode(1, 1, 0, ["London", 5])
    json_req = json.dumps({
        "function": "get_forecast",
        "city": "London",
        "days": 5,
    })
    result = api.get_forecast("London", 5)
    json_resp = json.dumps(result)
    codon_resp = encoder.encode(128, 1, 0, [json.dumps(result)], is_response=True)

    print(f"    Request:")
    print(f"      JSON:  {len(json_req)} bytes → ~{len(json_req)//4} tokens")
    print(f"      ANA:   {len(codon)} bytes → ~3 tokens (special)")
    print(f"    Response:")
    print(f"      JSON:  {len(json_resp)} bytes → ~{len(json_resp)//4} tokens")
    print(f"      ANA:   {len(codon_resp)} bytes → ~3 tokens (special)")
    print(f"    Total round-trip:")
    print(f"      JSON:  {len(json_req) + len(json_resp)} bytes")
    print(f"      ANA:   {len(codon) + len(codon_resp)} bytes")
    print(f"      Ratio: {(len(json_req) + len(json_resp)) / (len(codon) + len(codon_resp)):.1f}x")


if __name__ == '__main__':
    demo_api_handling()
