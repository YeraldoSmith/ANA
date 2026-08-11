"""Provider-neutral rendering of a selected ANA Envelope for text models."""

from __future__ import annotations

import json

from ana.schema import ANAEnvelope


def render_ana_prompt(envelope: ANAEnvelope) -> str:
    """Render the same already-selected ANA input for any text Provider.

    This is an adapter boundary helper, not a second Memory format: the source
    remains `ANAEnvelope.input` and `ANAEnvelope.context` in every case.
    """
    context = json.dumps(envelope.context, ensure_ascii=False, sort_keys=True)
    task_input = json.dumps(envelope.input, ensure_ascii=False, sort_keys=True)
    return (
        "You are a compute provider inside an ANA Local Runtime. "
        "Return the requested result only. Do not claim to have executed tools.\n"
        f"Intent: {envelope.intent}\n"
        f"Capabilities: {', '.join(envelope.capabilities)}\n"
        f"Input: {task_input}\n"
        f"Selected local context: {context}"
    )
