#!/usr/bin/env python3
"""
ANA Relay Middleware — Drop-in layer for existing relay stations.

Existing relays handle JSON function calls (OpenAI/Anthropic/Google format).
This middleware intercepts those calls, converts them to @s.o.t codon format,
and passes them through the ANA pipeline — then converts responses back.

The relay's existing code doesn't change. This sits alongside it.

Usage:
    from relay.middleware import ANARelayMiddleware

    mw = ANARelayMiddleware()
    mw.load_codebook("weather_service.yaml")

    # Convert JSON tool_call → @s.o.t codon
    codon_text = mw.json_to_codon(openai_tool_call)

    # Convert codon response → JSON
    json_resp = mw.codon_to_json(codon_response)
"""

import sys, os, re, json, time
from typing import Optional, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ana import Codebook, CodonEncoder, CodonDecoder


class ANARelayMiddleware:
    """
    Middleware that translates between JSON function calls and @s.o.t codons.

    Designed to sit alongside an existing relay station — not replace it.
    """

    def __init__(self):
        self.codebook: Optional[Codebook] = None
        self.encoder: Optional[CodonEncoder] = None
        self.decoder: Optional[CodonDecoder] = None
        self.stats = {
            'codon_calls': 0, 'json_calls': 0,
            'tokens_saved': 0, 'total_json_tokens': 0, 'total_codon_tokens': 0,
        }

    def load_codebook(self, yaml_path: str):
        """Load a codebook from YAML."""
        self.codebook = Codebook.from_yaml_file(yaml_path)
        self.encoder = CodonEncoder(self.codebook)
        self.decoder = CodonDecoder(self.codebook)
        return self

    # ── JSON → Codon ──────────────────────────────────────────────

    def json_to_codon(self, tool_call: dict) -> str:
        """
        Convert an OpenAI/Anthropic tool_call to @s.o.t codon text.

        Handles:
          - OpenAI: {"function": {"name": "svc.op", "arguments": "{...}"}}
          - Anthropic: {"name": "svc.op", "input": {...}}
        """
        name = self._extract_name(tool_call)
        args = self._extract_arguments(tool_call)

        # Find matching codon in codebook
        codon_id = self._find_codon(name, args)
        if codon_id is None:
            return None  # No matching codon — fall back to JSON

        svc_id, op_id, tpl_id = codon_id
        tpl = self.codebook.get_template(svc_id, op_id, tpl_id)

        # Build @s.o.t format
        param_values = []
        for pname in tpl.params:
            val = args.get(pname, tpl.defaults.get(pname, ''))
            param_values.append(str(val))

        codon_text = f'@{svc_id}.{op_id}.{tpl_id} ' + ' '.join(param_values)
        return codon_text.strip()

    def _extract_name(self, tool_call: dict) -> str:
        """Extract function name from various tool_call formats."""
        # OpenAI format
        if 'function' in tool_call:
            return tool_call['function'].get('name', '')
        # Anthropic format
        if 'name' in tool_call:
            return tool_call['name']
        # Direct
        return tool_call.get('function_name', '')

    def _extract_arguments(self, tool_call: dict) -> dict:
        """Extract arguments from various tool_call formats."""
        # OpenAI: arguments is a JSON string
        if 'function' in tool_call:
            args = tool_call['function'].get('arguments', '{}')
            if isinstance(args, str):
                try: return json.loads(args)
                except: return {}
            return args
        # Anthropic: input is a dict
        if 'input' in tool_call:
            return tool_call['input']
        # Direct
        return tool_call.get('arguments', tool_call.get('params', {}))

    def _find_codon(self, name: str, args: dict) -> Optional[tuple]:
        """Find the (svc_id, op_id, tpl_id) matching a function name and args."""
        parts = name.split('.')
        op_name = parts[-1] if len(parts) > 1 else name

        for svc in self.codebook.services.values():
            for op in svc.operations:
                if op.name == op_name or f'{svc.name}.{op.name}' == name:
                    # Find best template match based on arg keys
                    for tpl in op.templates:
                        arg_keys = set(args.keys())
                        tpl_keys = set(tpl.params)
                        if arg_keys == tpl_keys or tpl_keys.issubset(arg_keys):
                            return (svc.id, op.id, tpl.id)
                    # Fallback: first template
                    if op.templates:
                        tpl = op.templates[0]
                        return (svc.id, op.id, tpl.id)
        return None

    # ── Codon → JSON ──────────────────────────────────────────────

    def codon_to_json(self, codon_text: str) -> dict:
        """
        Convert a @s.o.t codon response back to OpenAI-compatible JSON.
        """
        m = re.match(r'@(\d+)\.(\d+)\.(\d+)\s*(.*)', codon_text.strip())
        if not m:
            return {'error': 'invalid codon format'}

        svc_id, op_id, tpl_id = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result_text = m.group(4).strip()

        return {
            'id': f'call_codon_{svc_id}_{op_id}',
            'type': 'function',
            'function': {
                'name': f'{self.codebook.get_service(svc_id).name}.{self.codebook.get_operation(svc_id, op_id).name}',
                'arguments': result_text,
            }
        }

    # ── Stats ─────────────────────────────────────────────────────

    def record_call(self, json_tokens: int, codon_tokens: int):
        self.stats['codon_calls'] += 1
        self.stats['total_json_tokens'] += json_tokens
        self.stats['total_codon_tokens'] += codon_tokens
        self.stats['tokens_saved'] += (json_tokens - codon_tokens)

    def get_stats(self) -> dict:
        s = self.stats
        total = max(s['codon_calls'] + s['json_calls'], 1)
        return {
            **s,
            'avg_saved_per_call': round(s['tokens_saved'] / max(s['codon_calls'], 1), 1),
            'reduction_pct': round((1 - s['total_codon_tokens'] / max(s['total_json_tokens'], 1)) * 100, 1),
        }

    # ── System prompt generator ───────────────────────────────────

    def generate_system_prompt(self) -> str:
        """Generate a system prompt that tells the LLM to use @s.o.t format."""
        lines = [
            "When calling functions, use this EXACT format on a single line:",
            "@service.operation.template param1 param2 ...",
            "",
            "Available functions:",
        ]
        for svc in self.codebook.services.values():
            for op in svc.operations:
                for tpl in op.templates:
                    example_params = ' '.join(
                        str(tpl.defaults.get(p, f'<{p}>')) for p in tpl.params
                    )
                    lines.append(
                        f"  @{svc.id}.{op.id}.{tpl.id} {example_params}"
                        f"  — {svc.name}.{op.name}({', '.join(tpl.params)})"
                    )
        lines.extend([
            "",
            "RULES:",
            "- Output ONLY the @ line. No markdown, no JSON, no explanation.",
            "- String parameters do NOT need quotes.",
            "- Separate parameters with spaces.",
            "- If the user doesn't specify a parameter, use the default shown above."
        ])
        return '\n'.join(lines)
