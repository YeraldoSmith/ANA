"""Deterministic adapter used to prove the v0.1 end-to-end boundary."""

from __future__ import annotations

from ana.schema import ANAEnvelope, ProposedAction, ProviderResult


class MockCodeProvider:
    provider_id = "ana.mock-code.v0"
    capabilities = frozenset({"code_generation"})

    def run(self, envelope: ANAEnvelope) -> ProviderResult:
        if "code_generation" not in envelope.capabilities:
            raise ValueError("mock provider only supports code generation")
        language = envelope.context.get("language", "java").lower()
        if language != "java":
            raise ValueError("MVP mock supports Java only")
        source = (
            "public class Hello {\n"
            "    public static void main(String[] args) {\n"
            "        System.out.println(\"Hello, ANA!\");\n"
            "    }\n"
            "}\n"
        )
        action = ProposedAction(kind="write_file", target="generated/Hello.java", content=source)
        return ProviderResult(
            provider_id=self.provider_id,
            output={"text": "Generated a Java hello-world program.", "artifacts": ["generated/Hello.java"]},
            proposed_actions=(action,),
        )
