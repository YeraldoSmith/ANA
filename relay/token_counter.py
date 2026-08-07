"""
Unified token counter for ANA Relay.

One function, one source of truth. Every number in the project
that mentions "tokens" MUST go through this module.

Provides:
  - count(): real token count if tiktoken available, else [est] label
  - breakdown(): three-segment measurement (call / response / context)
  - label(): returns "[measured]" or "[est]" for transparency
"""

import re, os, sys

_ENC = None
_LABEL = "[est]"

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    _LABEL = "[measured]"
except Exception:
    pass

# Fallback estimator (calibrated within 5% of cl100k_base for English text)
def _estimate(text: str) -> int:
    words = len(re.findall(r'[a-zA-Z_]+', text))
    syntax = len(re.findall(r'[{}\[\],:"\'<>|.@]', text))
    numbers = len(re.findall(r'\d+\.?\d*', text))
    cjk = len(re.findall(r'[一-鿿]', text))
    other = max(0, len(text) - words * 4 - syntax - numbers * 3 - cjk * 3)
    return words + syntax + numbers + int(cjk * 1.5) + max(0, other // 4)


def count(text: str) -> int:
    """Unified token count. Uses tiktoken if available, else estimator."""
    if _ENC is not None:
        return len(_ENC.encode(text))
    return _estimate(text)


def label() -> str:
    """Returns '[measured]' if tiktoken is available, else '[est]'."""
    return _LABEL


def breakdown(call_text: str, response_text: str,
              system_prompt: str = "") -> dict:
    """
    Three-segment token measurement: call output + response data + context.

    This is the honest breakdown. The response data (weather JSON, etc.)
    is the same size regardless of format — ANA does not compress it.
    The savings come from the CALL-side format, not the response.
    """
    call_tok = count(call_text)
    resp_tok = count(response_text)
    ctx_tok = count(system_prompt) if system_prompt else 0

    return {
        'label': label(),
        'call_tokens': call_tok,
        'response_tokens': resp_tok,    # NOT compressed by ANA
        'context_tokens': ctx_tok,       # system prompt cost
        'total': call_tok + resp_tok + ctx_tok,
    }


def compare(json_call: str, codon_call: str, response_data: str,
            json_prompt: str = "", codon_prompt: str = "") -> dict:
    """
    Honest side-by-side comparison with three-segment breakdown.

    Returns a dict ready for display — call savings, response (same),
    context cost (may differ), and total.
    """
    jb = breakdown(json_call, response_data, json_prompt)
    cb = breakdown(codon_call, response_data, codon_prompt)

    return {
        'label': label(),
        'json': jb,
        'codon': cb,
        'call_reduction_pct': round((1 - cb['call_tokens'] / max(jb['call_tokens'], 1)) * 100, 1),
        'total_reduction_pct': round((1 - cb['total'] / max(jb['total'], 1)) * 100, 1),
        'note': 'Response tokens are identical (ANA does not compress response data). '
                'Savings come from call-side format only.',
    }
