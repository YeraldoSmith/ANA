"""
JSON fallback handling for ANA Chain protocol.

When codon mode fails (codebook mismatch, unknown codon, etc.),
both sides can fall back to standard JSON-RPC over the existing transport.
"""

import json
from typing import Optional, Callable


class JSONFallbackCodec:
    """
    Encodes/decodes API operations as standard JSON-RPC 2.0.

    This is the "emergency mode" for ANA — used when codebook
    negotiation fails or during codebook version transitions.
    """

    JSONRPC_VERSION = "2.0"

    @staticmethod
    def encode_request(method: str, params: dict = None,
                       request_id: int = 1) -> bytes:
        """Encode a JSON-RPC request."""
        payload = {
            "jsonrpc": JSONFallbackCodec.JSONRPC_VERSION,
            "method": method,
            "id": request_id,
        }
        if params:
            payload["params"] = params
        return json.dumps(payload, ensure_ascii=False).encode('utf-8')

    @staticmethod
    def encode_response(result, request_id: int = 1) -> bytes:
        """Encode a JSON-RPC success response."""
        return json.dumps({
            "jsonrpc": JSONFallbackCodec.JSONRPC_VERSION,
            "result": result,
            "id": request_id,
        }, ensure_ascii=False).encode('utf-8')

    @staticmethod
    def encode_error(code: int, message: str, request_id: int = 1) -> bytes:
        """Encode a JSON-RPC error response."""
        return json.dumps({
            "jsonrpc": JSONFallbackCodec.JSONRPC_VERSION,
            "error": {"code": code, "message": message},
            "id": request_id,
        }, ensure_ascii=False).encode('utf-8')

    @staticmethod
    def decode(data: bytes) -> dict:
        """Decode a JSON-RPC message."""
        return json.loads(data.decode('utf-8'))


class FallbackHandler:
    """
    Manages the fallback lifecycle: detect, switch, recover.

    Usage:
        handler = FallbackHandler(
            fallback_send_fn=send_json_over_transport,
            fallback_recv_fn=recv_json_from_transport,
            renegotiate_fn=try_renegotiate_codebook,
        )

        # When a codon error occurs:
        handler.activate("codebook_mismatch")

        # Send operations in JSON mode:
        response = handler.call("get_weather", {"city": "Beijing"})

        # Try to switch back to codon mode:
        handler.try_recover()
    """

    def __init__(self,
                 fallback_send_fn: Callable[[bytes], None],
                 fallback_recv_fn: Callable[[], bytes],
                 renegotiate_fn: Optional[Callable[[], bool]] = None):
        """
        Args:
            fallback_send_fn: Function to send bytes over the transport.
            fallback_recv_fn: Function to receive bytes from the transport.
            renegotiate_fn: Function to attempt renegotiation. Returns True on success.
        """
        self._send = fallback_send_fn
        self._recv = fallback_recv_fn
        self._renegotiate = renegotiate_fn
        self._active = False
        self._request_counter = 0
        self.codec = JSONFallbackCodec()

    @property
    def is_active(self) -> bool:
        return self._active

    def activate(self, reason: str = "unknown"):
        """Switch to JSON fallback mode."""
        self._active = True
        self._request_counter = 0

    def deactivate(self):
        """Leave JSON fallback mode (codon mode restored)."""
        self._active = False

    def call(self, method: str, params: dict = None,
             timeout: float = 30.0) -> dict:
        """Make a synchronous JSON-RPC call in fallback mode.

        Args:
            method: The method/operation name.
            params: Parameters dict.
            timeout: Max wait time for response.

        Returns:
            The response result dict.
        """
        if not self._active:
            raise RuntimeError("FallbackHandler not active — call activate() first")

        self._request_counter += 1
        req_id = self._request_counter

        request_bytes = self.codec.encode_request(method, params, req_id)
        self._send(request_bytes)

        # Simple synchronous receive (in production, match request_id)
        response_bytes = self._recv()
        response = self.codec.decode(response_bytes)

        if "error" in response:
            raise RuntimeError(f"Fallback RPC error: {response['error']}")

        return response.get("result", {})

    def try_recover(self) -> bool:
        """Attempt to renegotiate codebook and exit fallback mode.

        Returns True if recovery succeeded.
        """
        if self._renegotiate is None:
            return False
        try:
            success = self._renegotiate()
            if success:
                self._active = False
            return success
        except Exception:
            return False
