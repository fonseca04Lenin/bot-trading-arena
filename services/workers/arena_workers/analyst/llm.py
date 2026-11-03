"""LLM client protocol with a live Anthropic implementation and cassette record/replay for CI."""

import json
from pathlib import Path
from typing import Any, Protocol

Message = dict[str, Any]


class LLMResponse:
    def __init__(self, content: list[dict[str, Any]], stop_reason: str, input_tokens: int = 0,
                 output_tokens: int = 0) -> None:
        self.content, self.stop_reason = content, stop_reason
        self.input_tokens, self.output_tokens = input_tokens, output_tokens

    def to_json(self) -> dict[str, Any]:
        return {"content": self.content, "stop_reason": self.stop_reason,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "LLMResponse":
        return cls(d["content"], d["stop_reason"], d.get("input_tokens", 0), d.get("output_tokens", 0))


class LLMClient(Protocol):
    def create(self, system: str, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse: ...


class AnthropicClient:
    def __init__(self, model: str, api_key: str) -> None:
        import anthropic
        self.client: Any = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def create(self, system: str, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        resp = self.client.messages.create(
            model=self.model, max_tokens=8000, system=system, tools=tools,
            messages=messages,
            thinking={"type": "adaptive"}, output_config={"effort": "medium"},
        )
        content = [b.model_dump(exclude_none=True) for b in resp.content]
        return LLMResponse(content, resp.stop_reason or "end_turn", resp.usage.input_tokens, resp.usage.output_tokens)


class CassetteClient:
    """Replays recorded responses in order; raises if the agent asks for more than was recorded."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses, self.i = responses, 0

    @classmethod
    def load(cls, path: Path) -> "CassetteClient":
        data = json.loads(path.read_text())
        return cls([LLMResponse.from_json(r) for r in data["responses"]])

    def create(self, system: str, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        if self.i >= len(self.responses):
            raise RuntimeError("cassette exhausted: the agent made more calls than were recorded")
        r = self.responses[self.i]
        self.i += 1
        return r


class RecordingClient:
    def __init__(self, inner: LLMClient) -> None:
        self.inner, self.recorded = inner, []  # type: ignore[var-annotated]

    def create(self, system: str, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        r = self.inner.create(system, messages, tools)
        self.recorded.append(r)
        return r

    def save(self, path: Path, source: str, model: str) -> None:
        path.write_text(json.dumps({"source": source, "model": model,
                                    "responses": [r.to_json() for r in self.recorded]}, indent=1) + "\n")
