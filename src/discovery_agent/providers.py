"""LLM providers.

Every provider implements one method::

    generate(step=..., system=..., prompt=..., schema=SomePydanticModel) -> SomePydanticModel

so the pipeline never depends on a specific vendor. Available providers:

* ``claude``  - Anthropic API (default). Structured output via forced tool use.
* ``gemini``  - Google Gemini API (has a free tier). JSON mode.
* ``ollama``  - Local models through Ollama. Free, runs on your machine.
* ``demo``    - Replays saved responses for the bundled examples. No key needed.

``RecordingProvider`` wraps any provider and saves its responses, which is how
the demo fixtures are produced.
"""

from __future__ import annotations

import copy
import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODELS = {
    "claude": "claude-sonnet-5-5",
    "gemini": "gemini-2.5-flash",
    "ollama": "llama3.1",
}


class ProviderError(RuntimeError):
    """Raised when a provider can't produce a response."""


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return the model's JSON schema with every ``$ref`` resolved inline.

    Some APIs handle ``$defs``/``$ref`` poorly, so we always send a flat schema.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return resolve(copy.deepcopy(defs[name]))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def parse_json_text(text: str) -> Any:
    """Parse JSON from a model reply, tolerating ```json fences and extra prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(text[start : end + 1])


class BaseProvider:
    name = "base"

    def __init__(self, model: str | None = None):
        self.model = model or DEFAULT_MODELS.get(self.name, "")

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}" if self.model else self.name

    def generate(self, *, step: str, system: str, prompt: str, schema: type[T]) -> T:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Claude
# --------------------------------------------------------------------------- #


class ClaudeProvider(BaseProvider):
    """Anthropic Claude via the official SDK, using forced tool use for structured output."""

    name = "claude"

    def __init__(self, model: str | None = None, api_key: str | None = None, client: Any = None):
        super().__init__(model or os.getenv("DISCOVERY_MODEL"))
        if client is not None:
            self.client = client
            return
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ProviderError("Install the Anthropic SDK: pip install anthropic") from exc
        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file, or run with "
                "--provider demo to try the bundled example without a key."
            )
        self.client = anthropic.Anthropic(api_key=key)

    def generate(self, *, step: str, system: str, prompt: str, schema: type[T]) -> T:
        tool = {
            "name": "submit_result",
            "description": f"Submit the result of the '{step.split(':')[0]}' step.",
            "input_schema": inline_schema(schema),
        }
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            temperature=0,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": "submit_result"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use":
                return schema.model_validate(block.input)
        raise ProviderError(f"Claude returned no structured result for step '{step}'.")


# --------------------------------------------------------------------------- #
# Gemini (free tier available)
# --------------------------------------------------------------------------- #


class GeminiProvider(BaseProvider):
    """Google Gemini via the google-genai SDK, in JSON mode."""

    name = "gemini"

    def __init__(self, model: str | None = None, api_key: str | None = None, client: Any = None):
        super().__init__(model or os.getenv("DISCOVERY_MODEL"))
        if client is not None:
            self.client = client
            return
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("Install the Gemini SDK: pip install google-genai") from exc
        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY is not set.")
        self.client = genai.Client(api_key=key)

    def generate(self, *, step: str, system: str, prompt: str, schema: type[T]) -> T:
        schema_txt = json.dumps(inline_schema(schema), indent=2)
        full_system = (
            f"{system}\n\nReply with a single JSON object that matches this JSON schema:\n{schema_txt}"
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={
                "system_instruction": full_system,
                "response_mime_type": "application/json",
                "temperature": 0,
            },
        )
        return schema.model_validate(parse_json_text(response.text))


# --------------------------------------------------------------------------- #
# Ollama (local, free)
# --------------------------------------------------------------------------- #


class OllamaProvider(BaseProvider):
    """Local models served by Ollama (https://ollama.com). Uses structured outputs."""

    name = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None):
        super().__init__(model or os.getenv("DISCOVERY_MODEL"))
        self.host = (host or os.getenv("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")

    def generate(self, *, step: str, system: str, prompt: str, schema: type[T]) -> T:
        payload = {
            "model": self.model,
            "stream": False,
            "format": inline_schema(schema),
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 - local URL
                body = json.loads(resp.read())
        except OSError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self.host}. Is it running? (ollama serve)"
            ) from exc
        return schema.model_validate(parse_json_text(body["message"]["content"]))


# --------------------------------------------------------------------------- #
# Demo and recording
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"
DEMO_FIXTURES = EXAMPLES_DIR / "demo_fixtures.json"


class DemoProvider(BaseProvider):
    """Replays saved responses so the full pipeline runs without an API key.

    Responses are keyed by pipeline step, so demo mode only works with the
    bundled example interviews in ``examples/interviews``.
    """

    name = "demo"

    def __init__(self, fixtures_path: str | Path | None = None):
        super().__init__(model="")
        path = Path(fixtures_path or DEMO_FIXTURES)
        if not path.exists():
            raise ProviderError(f"Demo fixtures not found at {path}.")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.recorded_with = data.get("recorded_with", "unknown")
        self.responses: dict[str, Any] = data["responses"]

    @property
    def label(self) -> str:
        return f"demo (replaying {self.recorded_with})"

    def generate(self, *, step: str, system: str, prompt: str, schema: type[T]) -> T:
        if step not in self.responses:
            raise ProviderError(
                f"Demo mode has no saved response for step '{step}'. Demo mode only works with "
                "the bundled example interviews. Use a real provider for your own data."
            )
        return schema.model_validate(self.responses[step])


class RecordingProvider(BaseProvider):
    """Wraps another provider and records every response to a JSON file."""

    def __init__(self, inner: BaseProvider, path: str | Path):
        super().__init__(model=inner.model)
        self.inner = inner
        self.name = inner.name
        self.path = Path(path)
        self.responses: dict[str, Any] = {}

    @property
    def label(self) -> str:
        return self.inner.label

    def generate(self, *, step: str, system: str, prompt: str, schema: type[T]) -> T:
        result = self.inner.generate(step=step, system=system, prompt=prompt, schema=schema)
        self.responses[step] = result.model_dump()
        self.save()
        return result

    def save(self) -> None:
        payload = {"recorded_with": self.inner.label, "responses": self.responses}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def get_provider(name: str, model: str | None = None, api_key: str | None = None) -> BaseProvider:
    name = name.lower()
    if name == "claude":
        return ClaudeProvider(model=model, api_key=api_key)
    if name == "gemini":
        return GeminiProvider(model=model, api_key=api_key)
    if name == "ollama":
        return OllamaProvider(model=model)
    if name == "demo":
        return DemoProvider()
    raise ProviderError(f"Unknown provider '{name}'. Choose claude, gemini, ollama or demo.")
