import json
import re
import urllib.request

import pytest
from atoms_mul.analysis.llm_policy import LLMPolicy, extract_program
from atoms_mul.harness.run import run


@pytest.mark.parametrize("reply,expected", [
    ("def solve(x) = x", "def solve(x) = x"),
    ("Here is AML:\n```aml\ndef solve(x) = add(x, x)\n```\nThanks.",
     "def solve(x) = add(x, x)"),
    ("```\ndef solve(x) = 0\n```", "def solve(x) = 0"),
])
def test_extract_program(reply, expected):
    assert extract_program(reply) == expected


def test_api_opt_in_and_no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Unexpected network request")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="allow_api"):
        LLMPolicy(model="test-model")
    monkeypatch.delenv("ATOMS_MUL_TEST_MISSING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Missing API key"):
        LLMPolicy(allow_api=True, model="test-model",
                  api_key_env="ATOMS_MUL_TEST_MISSING_KEY")


class _FakeResponse:
    def __init__(self, content):
        self.body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def read(self, *args):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_real_run_path_end_to_end_with_fake_endpoint(monkeypatch, tmp_path):
    """The exact `--policy llm` path, with the HTTP call replaced by a local fake."""
    seen = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data)
        seen.append(payload)
        assert request.full_url == "http://fake.invalid/v1/chat/completions"
        assert payload["model"] == "fake-model" and len(payload["messages"]) == 1
        params = re.search(r"defining solve\(([^)]*)\)", payload["messages"][0]["content"])
        first = params.group(1).split(", ")[0]
        if len(seen) == 1:
            raise OSError("transient")  # retried inside the policy, not an api_error
        return _FakeResponse(f"```aml\ndef solve({params.group(1)}) = {first}\n```")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("ATOMS_MUL_FAKE_KEY", "not-a-real-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://fake.invalid/v1")
    monkeypatch.setattr(LLMPolicy.__init__, "__kwdefaults__",
                        {**LLMPolicy.__init__.__kwdefaults__, "api_key_env": "ATOMS_MUL_FAKE_KEY"})
    out = run(policy="llm", allow_api=True, model="fake-model", groups=["C"], episodes=1,
              run_id="fake", out=tmp_path, max_attempts=2)
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 40 and not any(row.get("api_error") for row in rows)
    assert all(row["attempts"] == 2 and not row["correct"] for row in rows)
    assert json.loads((out / "config.json").read_text())["model"] == "fake-model"
    assert all("not-a-real-key" not in json.dumps(payload) for payload in seen)
