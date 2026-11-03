"""One agent run: tool loop, then guardrail review. Pure of I/O apart from the injected client and view."""

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from .guardrails import Decision, Review, review
from .llm import LLMClient, LLMResponse
from .tools import TOOLS, ToolBox
from .version import PROMPT_VERSION
from .views import MarketView

MAX_ROUNDS = 8


def load_prompt() -> str:
    return resources.files(__package__).joinpath("prompt.md").read_text()


@dataclass
class RunResult:
    review: Review
    transcript: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_version: str = PROMPT_VERSION

    @property
    def approved(self) -> list[Decision]:
        return self.review.approved


def run_agent(client: LLMClient, view: MarketView) -> RunResult:
    tools = ToolBox(view)
    messages: list[dict[str, Any]] = [{"role": "user", "content":
        f"Review the portfolio and the market. Market is {'open' if view.market_open() else 'closed'} for equities; crypto trades 24/7."}]
    result = RunResult(Review(valid=False, error="no_submission"))
    for _ in range(MAX_ROUNDS):
        resp: LLMResponse = client.create(load_prompt(), messages, TOOLS)
        result.input_tokens += resp.input_tokens
        result.output_tokens += resp.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        calls = [b for b in resp.content if b.get("type") == "tool_use"]
        if not calls:
            result.review = Review(valid=False, error="model_stopped_without_submitting")
            break
        submit = next((c for c in calls if c["name"] == "submit_decisions"), None)
        if submit:
            result.review = review(submit["input"], tools, view.portfolio(), view.market_open())
            break
        results = [{"type": "tool_result", "tool_use_id": c["id"],
                    "content": json.dumps(tools.call(c["name"], c.get("input", {})))} for c in calls]
        messages.append({"role": "user", "content": results})
    else:
        result.review = Review(valid=False, error="too_many_rounds")
    result.transcript = messages
    return result
