"""Review checks for machine-track hardening and shared harness behavior."""

import io
import json
import random

import pytest
from atoms_mul.analysis.analyze import analyze
from atoms_mul.analysis.llm_policy import extract_program
from atoms_mul.harness.env import run_episode as aml_episode
from atoms_mul.harness.run import run
from atoms_mul.machine.check import check_program
from atoms_mul.machine.env import run_episode as machine_episode
from atoms_mul.machine.lang import MasmSyntaxError, parse_program
from atoms_mul.machine.library import Library


class Static:
    name = "static"

    def reset(self, **kwargs):
        pass

    def act(self, observation):
        return ("sub main:\n  halt\nend" if "registers" in observation["task"]["public_examples"][0]
                else "def solve(x) = 0")


def test_env_record_keys_match():
    aml = {"id": "sample", "family": "constant_scale", "statement": "Return zero.",
           "params": ["x"], "solve_signature": "solve(x)",
           "public_examples": [{"args": [0], "expected": 0}],
           "hidden_tests": [{"args": [0], "expected": 0}]}
    machine = {"id": "sample", "family": "constant_scale", "statement": "Return zero.",
               "public_examples": [{"registers": [0, 0, 0, 0], "memory": {}, "expected_r0": 0}],
               "hidden_tests": [{"registers": [0, 0, 0, 0], "memory": {}, "expected_r0": 0}]}
    aml_record = aml_episode(Static(), "C", 0, [aml], [], max_attempts=1)[0]
    machine_record = machine_episode(Static(), "C", 0, [machine], [], max_attempts=1)[0]
    assert set(machine_record) == set(aml_record) | {"track"}


def test_parser_fuzz_and_checks():
    rng = random.Random(8167)
    alphabet = "\u00e9\u200b\U0001f642\u06609r:,#\n ()_abc"
    cases = ["9" * 5000, "sub main:\n set r0, " + "9" * 5000 + "\nend",
             "sub main:\n" + "  jz r1, LOOP\n" * 5000 + "end",
             "sub main:\n" + "  set r0, 0\n" * 5000 + "end"]
    cases += ["".join(rng.choices(alphabet, k=rng.randrange(1000))) for _ in range(250)]
    for source in cases:
        try:
            program = parse_program(source)
            assert isinstance(check_program(program, "B", Library()), list)
        except MasmSyntaxError:
            pass
    duplicate = parse_program("sub main:\nend\nsub helper:\nend\nsave helper\nsave helper")
    assert "duplicate save" in check_program(duplicate, "B", Library())
    huge = parse_program("sub main:\n set r0, " + "9" * 5000 + "\nend")
    assert any("out of range" in error for error in check_program(huge, "B", Library()))


def test_analysis_rejects_mixed_tracks():
    with pytest.raises(ValueError, match="more than one track"):
        analyze([{"track": "aml"}, {"track": "machine"}])


def test_machine_fake_endpoint(monkeypatch, tmp_path):
    seen = []

    def opener(request, timeout):
        seen.append(json.loads(request.data))
        if len(seen) == 1:
            raise OSError("transient")
        return io.BytesIO(b'{"choices":[{"message":{"content":"```masm\\nsub main:\\n  halt\\nend\\n```"}}]}')

    monkeypatch.setattr("urllib.request.urlopen", opener)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-only")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://fake.invalid/v1")
    assert extract_program("```masm\nsub main:\n  halt\nend\n```") == "sub main:\n  halt\nend"
    result = run(track="machine", policy="llm", allow_api=True, model="fake-model",
                 groups=["C"], episodes=1, run_id="fake-machine", out=tmp_path, max_attempts=1)
    rows = [json.loads(line) for line in (result / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 40 and all(not row.get("api_error") for row in rows)
    assert all(row["track"] == "machine" for row in rows)
    assert json.loads((result / "config.json").read_text())["track"] == "machine"
    assert all(row["track"] == "machine" for row in map(json.loads, (result / "prompts.jsonl").read_text().splitlines()))
    assert len(seen) == 41 and seen[0]["seed"] == 201000


def test_machine_api_error_does_not_consume_attempts():
    class Broken(Static):
        name = "llm"

        def act(self, observation):
            raise OSError("endpoint unavailable")

    machine = {"id": "sample", "family": "constant_scale", "statement": "Return zero.",
               "public_examples": [{"registers": [0, 0, 0, 0], "memory": {}, "expected_r0": 0}],
               "hidden_tests": [{"registers": [0, 0, 0, 0], "memory": {}, "expected_r0": 0}]}
    row = machine_episode(Broken(), "C", 0, [machine], [machine])[0]
    assert row["api_error"] and row["attempts"] == 1 and row["check_errors"] == 0


def test_machine_resume_and_track_mismatch(monkeypatch, tmp_path):
    from atoms_mul.machine import env

    calls = []
    original = env.run_episode

    def counting(*args, **kwargs):
        calls.append((args[1], args[2]))
        return original(*args, **kwargs)

    monkeypatch.setattr(env, "run_episode", counting)
    options = {"track": "machine", "policy": "unroll", "groups": ["A"], "episodes": 1,
               "run_id": "resume-machine", "out": tmp_path, "max_attempts": 1}
    run(**options)
    assert calls == [("A", 0)]
    run(**options, resume=True)
    assert calls == [("A", 0)]
    with pytest.raises(ValueError, match="config mismatch: track"):
        run(**{**options, "track": "aml"}, resume=True)
