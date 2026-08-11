"""Independent ANA Node B implementation for the v0.1 minimal profile.

This module intentionally does not import the reference ANA runtime or Node A.
"""

from __future__ import annotations

import json
from typing import Any


class NodeBProtocolError(ValueError):
    """Raised when Node B cannot accept a v0.1 minimal-profile task frame."""


def canonical(value: Any) -> str:
    """Node B's own canonical JSON implementation."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _read_frame(wire: bytes) -> dict[str, Any]:
    try:
        decoded = wire.decode("utf-8")
        frame = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NodeBProtocolError("invalid UTF-8 JSON frame") from error
    if not isinstance(frame, dict):
        raise NodeBProtocolError("frame must be a JSON object")
    if canonical(frame).encode("utf-8") != wire:
        raise NodeBProtocolError("frame is not canonical JSON")
    return frame


def receive_envelope(wire: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Decode a Node A frame without using Node A's encoding functions."""
    frame = _read_frame(wire)
    expected = {
        "protocol_version": "0.1",
        "chain_id": "ana-core-chain",
        "chain_version": "0.1",
        "dictionary_id": None,
        "dictionary_version": None,
        "payload_type": "envelope",
        "transforms": [],
    }
    if any(frame.get(key) != value for key, value in expected.items()):
        raise NodeBProtocolError("unsupported ANA Chain profile")
    if not isinstance(frame.get("message_id"), str) or not frame["message_id"]:
        raise NodeBProtocolError("missing message_id")
    if not isinstance(frame.get("stream_id"), str) or not frame["stream_id"]:
        raise NodeBProtocolError("missing stream_id")
    if frame.get("sequence") != 0 or not isinstance(frame.get("payload"), str):
        raise NodeBProtocolError("invalid initial task frame")
    try:
        envelope = json.loads(frame["payload"])
    except json.JSONDecodeError as error:
        raise NodeBProtocolError("envelope payload is invalid JSON") from error
    if not isinstance(envelope, dict) or canonical(envelope) != frame["payload"]:
        raise NodeBProtocolError("envelope payload is not canonical")
    required = ("version", "task_id", "intent", "capabilities", "input")
    if any(key not in envelope for key in required) or envelope.get("version") != "0.1":
        raise NodeBProtocolError("invalid v0.1 envelope")
    if (
        not isinstance(envelope["task_id"], str)
        or not envelope["task_id"]
        or not isinstance(envelope["intent"], str)
        or not envelope["intent"]
        or frame["stream_id"] != envelope["task_id"]
        or not isinstance(envelope["capabilities"], list)
        or not envelope["capabilities"]
        or not all(isinstance(capability, str) and capability for capability in envelope["capabilities"])
        or not isinstance(envelope["input"], dict)
        or ("context" in envelope and not isinstance(envelope["context"], dict))
        or (
            "memory_refs" in envelope
            and (
                not isinstance(envelope["memory_refs"], list)
                or not all(isinstance(reference, str) for reference in envelope["memory_refs"])
            )
        )
        or ("policy" in envelope and not isinstance(envelope["policy"], dict))
    ):
        raise NodeBProtocolError("envelope violates minimal profile")
    return envelope, frame


def build_routed_state_delta(
    envelope: dict[str, Any], task_frame: dict[str, Any], state_frame: dict[str, Any]
) -> bytes:
    """Create the minimal project-state delta caused by accepting a task."""
    if state_frame.get("stream_id") != envelope["task_id"]:
        raise NodeBProtocolError("state delta must remain in the task stream")
    if state_frame.get("sequence") != task_frame["sequence"] + 1:
        raise NodeBProtocolError("state delta must immediately follow the task frame")
    if not isinstance(state_frame.get("message_id"), str) or not state_frame["message_id"]:
        raise NodeBProtocolError("state delta requires a message_id")
    delta = {
        "event_id": f"evt-{envelope['task_id']}-project-state",
        "stream_id": envelope["task_id"],
        "parent_event_id": task_frame["message_id"],
        "sequence": state_frame["sequence"],
        "kind": "project_state.upsert",
        "payload": {
            "task_id": envelope["task_id"],
            "status": "routed",
            "required_capabilities": envelope["capabilities"],
        },
    }
    outgoing = {
        "protocol_version": "0.1",
        "chain_id": "ana-core-chain",
        "chain_version": "0.1",
        "dictionary_id": None,
        "dictionary_version": None,
        "message_id": state_frame["message_id"],
        "stream_id": state_frame["stream_id"],
        "sequence": state_frame["sequence"],
        "payload_type": "state_delta",
        "payload": canonical(delta),
        "transforms": [],
    }
    return canonical(outgoing).encode("utf-8")
