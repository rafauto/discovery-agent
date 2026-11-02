import json
from types import SimpleNamespace

import pytest

from discovery_agent.providers import (
    ClaudeProvider,
    DemoProvider,
    GeminiProvider,
    ProviderError,
    RecordingProvider,
    get_provider,
    inline_schema,
    parse_json_text,
)
from discovery_agent.schemas import PainExtraction, StoryBatch

PAIN = {"statement": "s", "quote": "q", "persona": "p", "severity": 3}


def test_inline_schema_has_no_refs():
    schema = inline_schema(StoryBatch)
    assert "$ref" not in json.dumps(schema)
    assert "$defs" not in schema
    criteria = schema["properties"]["stories"]["items"]["properties"]["acceptance_criteria"]
    assert criteria["items"]["properties"]["given"]["type"] == "string"


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Sure! Here it is: {"a": 1} Hope it helps.',
    ],
)
def test_parse_json_text(text):
    assert parse_json_text(text) == {"a": 1}


class FakeAnthropic:
    def __init__(self, payload):
        self.payload = payload
        self.kwargs = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="thinking..."),
                SimpleNamespace(type="tool_use", input=self.payload),
            ]
        )


def test_claude_provider_forces_tool_use():
    client = FakeAnthropic({"pains": [PAIN]})
    provider = ClaudeProvider(model="claude-test", client=client)
    result = provider.generate(step="extract:x:0", system="sys", prompt="hi", schema=PainExtraction)
    assert result.pains[0].statement == "s"
    assert client.kwargs["tool_choice"] == {"type": "tool", "name": "submit_result"}
    assert client.kwargs["model"] == "claude-test"
    assert client.kwargs["system"] == "sys"


def test_claude_provider_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pytest.importorskip("anthropic")
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        ClaudeProvider()


def test_gemini_provider_parses_json():
    class Models:
        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(text=json.dumps({"pains": [PAIN]}))

    client = SimpleNamespace(models=Models())
    provider = GeminiProvider(model="gemini-test", client=client)
    result = provider.generate(step="s", system="sys", prompt="p", schema=PainExtraction)
    assert result.pains[0].severity == 3
    assert client.models.kwargs["config"]["response_mime_type"] == "application/json"


def test_demo_provider_rejects_unknown_steps():
    provider = DemoProvider()
    with pytest.raises(ProviderError, match="bundled example"):
        provider.generate(step="extract:my_file:0", system="", prompt="", schema=PainExtraction)


def test_recording_provider_writes_fixtures(tmp_path, fake_provider_cls):
    inner = fake_provider_cls({"cluster": {"pains": [PAIN]}})
    path = tmp_path / "rec.json"
    rec = RecordingProvider(inner, path)
    rec.generate(step="cluster", system="", prompt="", schema=PainExtraction)
    data = json.loads(path.read_text())
    assert data["responses"]["cluster"]["pains"][0]["quote"] == "q"
    assert data["recorded_with"] == "fake:test"


def test_unknown_provider():
    with pytest.raises(ProviderError):
        get_provider("gpt")
