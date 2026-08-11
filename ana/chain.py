"""Reversible ANA Chain reference codec; it provides no confidentiality."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EncodedStream:
    payload: bytes
    operations: tuple[str, ...]


class ANAChain:
    _valid = frozenset({"reverse", "rotate_left", "xor_a5"})

    @classmethod
    def encode(cls, text: str, operations: tuple[str, ...] = ("reverse", "rotate_left")) -> EncodedStream:
        data = text.encode("utf-8")
        cls._validate(operations)
        for operation in operations:
            data = cls._apply(data, operation)
        return EncodedStream(payload=data, operations=operations)

    @classmethod
    def decode(cls, stream: EncodedStream) -> str:
        cls._validate(stream.operations)
        data = stream.payload
        for operation in reversed(stream.operations):
            data = cls._undo(data, operation)
        return data.decode("utf-8")

    @classmethod
    def _validate(cls, operations: tuple[str, ...]) -> None:
        unknown = set(operations) - cls._valid
        if unknown:
            raise ValueError(f"unsupported operations: {sorted(unknown)}")

    @staticmethod
    def _apply(data: bytes, operation: str) -> bytes:
        if operation == "reverse":
            return data[::-1]
        if operation == "rotate_left":
            return data[1:] + data[:1] if data else data
        return bytes(value ^ 0xA5 for value in data)

    @staticmethod
    def _undo(data: bytes, operation: str) -> bytes:
        if operation == "reverse":
            return data[::-1]
        if operation == "rotate_left":
            return data[-1:] + data[:-1] if data else data
        return bytes(value ^ 0xA5 for value in data)
