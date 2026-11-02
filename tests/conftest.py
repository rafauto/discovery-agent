from __future__ import annotations

from typing import Any

import pytest

from discovery_agent.providers import BaseProvider


class FakeProvider(BaseProvider):
    """Returns scripted responses per step and records every call."""

    name = "fake"

    def __init__(self, responses: dict[str, Any]):
        super().__init__(model="test")
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, step, system, prompt, schema):
        self.calls.append({"step": step, "system": system, "prompt": prompt})
        value = self.responses[step]
        if isinstance(value, list):  # a list = successive answers for retries
            value = value.pop(0)
        return schema.model_validate(value)


@pytest.fixture
def fake_provider_cls():
    return FakeProvider
