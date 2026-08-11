"""Independent ANA Node A implementation for the v0.1 minimal profile.

This module intentionally does not import the reference ANA runtime or Node B.
"""

from __future__ import annotations

import json
from typing import Any


class NodeAProtocolError(ValueError):
    """Raised when a v0.1 minimal-profile frame is invalid."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_json_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as error:
        raise NodeAProtocolError("payload is not valid JSON text") from error
    if not isinstance(value, dict):
        raise NodeAProtocolError("payload must decode to an object")
    return value


def _validate_envelope(envelope: dict[str, Any]) -> None:
    required = ("version", "task_id", "intent", "capabilities", "input")
    if any(field not in envelope for field in required):
        raise NodeAProtocolError("envelope misses a required field")
    if envelope["version"] != "0.1":
        raise NodeAProtocolError("unsupported envelope version")
    if not isinstance(envelope["task_id"], str) or not envelope["task_id"]:
        raise NodeAProtocolError("task_id must be a non-empty string")
    if not isinstance(envelope["intent"], str) or not envelope["intent"]:
        raise NodeAProtocolError("intent must be a non-empty string")
    capabilities = envelope["capabilities"]
    if not isinstance(capabilities, list) or not capabilities or not all(
        isinstance(capability, str) and capability for capability in capabilities
    ):
        raise NodeAProtocolError("capabilities must contain non-empty strings")
    if not isinstance(envelope["input"], dict):
        raise NodeAProtocolError("input must be an object")
    if "context" in envelope and not isinstance(envelope["context"], dict):
        raise NodeAProtocolError("context must be an object")
    if "memory_refs" in envelope and (
        not isinstance(envelope["memory_refs"], list)
        or not all(isinstance(reference, str) for reference in envelope["memory_refs"])
    ):
        raise NodeAProtocolError("memory_refs must be an array of strings")
    if "policy" in envelope and not isinstance(envelope["policy"], dict):
        raise NodeAProtocolError("policy must be an object")


def build_envelope_wire(envelope: dict[str, Any], frame: dict[str, Any]) -> bytes:
    """Build a canonical `ana-core-chain` envelope frame from local task data."""
    _validate_envelope(envelope)
    if frame.get("stream_id") != envelope["task_id"] or frame.get("sequence") != 0:
        raise NodeAProtocolError("initial task frame must use its task_id and sequence 0")
    if not isinstance(frame.get("message_id"), str) or not frame["message_id"]:
        raise NodeAProtocolError("frame requires a non-empty message_id")
    wire_frame = {
        "protocol_version": "0.1",
        "chain_id": "ana-core-chain",
        "chain_version": "0.1",
        "dictionary_id": None,
        "dictionary_version": None,
        "message_id": frame["message_id"],
        "stream_id": frame["stream_id"],
        "sequence": frame["sequence"],
        "payload_type": "envelope",
        "payload": _canonical_json(envelope),
        "transforms": [],
    }
    return _canonical_json(wire_frame).encode("utf-8")


def receive_state_delta(
    wire: bytes, *, expected_stream_id: str, previous_message_id: str, previous_sequence: int
) -> dict[str, Any]:
    """Independently decode and validate Node B's State Delta frame."""
    try:
        frame = json.loads(wire.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NodeAProtocolError("wire frame is not UTF-8 JSON") from error
    if not isinstance(frame, dict):
        raise NodeAProtocolError("wire frame must be an object")
    if _canonical_json(frame).encode("utf-8") != wire:
        raise NodeAProtocolError("wire frame is not canonical JSON")
    required = {
        "protocol_version": "0.1",
        "chain_id": "ana-core-chain",
        "chain_version": "0.1",
        "dictionary_id": None,
        "dictionary_version": None,
        "payload_type": "state_delta",
        "transforms": [],
        "stream_id": expected_stream_id,
    }
    if any(frame.get(field) != expected for field, expected in required.items()):
        raise NodeAProtocolError("state delta frame is outside the v0.1 minimal profile")
    if not isinstance(frame.get("message_id"), str) or not frame["message_id"]:
        raise NodeAProtocolError("state delta frame requires message_id")
    if not isinstance(frame.get("sequence"), int) or frame["sequence"] <= previous_sequence:
        raise NodeAProtocolError("state delta sequence is not causally after the task frame")
    if not isinstance(frame.get("payload"), str):
        raise NodeAProtocolError("state delta payload must be JSON text")
    delta = _parse_json_text(frame["payload"])
    if _canonical_json(delta) != frame["payload"]:
        raise NodeAProtocolError("state delta payload is not canonical JSON")
    required_delta = {"event_id", "stream_id", "parent_event_id", "sequence", "kind", "payload"}
    if not required_delta.issubset(delta) or delta["kind"] != "project_state.upsert":
        raise NodeAProtocolError("unsupported state delta")
    if (
        delta["stream_id"] != expected_stream_id
        or delta["parent_event_id"] != previous_message_id
        or delta["sequence"] <= previous_sequence
        or delta["sequence"] != frame["sequence"]
        or not isinstance(delta["payload"], dict)
        or delta["payload"].get("task_id") != expected_stream_id
    ):
        raise NodeAProtocolError("state delta breaks the required causal relationship")
    return delta
