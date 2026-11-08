import json

from atoms_mul.analysis.cost import estimate
from atoms_mul.analysis.cost import main as cost_main
from atoms_mul.analysis.power import main as power_main
from atoms_mul.analysis.power import simulate_half_width


def test_cost_estimate_and_cli(tmp_path, capsys):
    prompts = tmp_path / "prompts.jsonl"
    data = [{"group": "B", "stage": 1, "task_id": "a", "attempt": 1, "prompt": "12345"},
            {"group": "B", "stage": 1, "task_id": "a", "attempt": 2, "prompt": "123456789"},
            {"group": "C", "stage": 2, "task_id": "b", "attempt": 1, "prompt": "1234"}]
    prompts.write_text("".join(json.dumps(row) + "\n" for row in data))
    result = estimate(data, episodes=2, groups=("B", "C"), attempts_mean=1.5,
                      max_output=10, price_in=2, price_out=4)
    assert result["expected_calls"] == 6
    assert result["worst_calls"] == 12
    assert result["expected_input_tokens"] == 10.5
    assert result["worst_input_tokens"] == 24
    assert result["expected_output_tokens"] == 60
    assert result["worst_output_tokens"] == 120
    assert result["expected_cost_usd"] == (10.5 * 2 + 60 * 4) / 1_000_000
    cost_main(["--prompts", str(prompts), "--episodes", "2", "--groups", "B,C",
               "--attempts-mean", "1.5", "--max-output", "10"])
    output = capsys.readouterr().out
    assert "Input tokens" in output and "Cost (USD)" not in output


def test_power_simulation_is_seeded_and_cli_runs(capsys):
    result = simulate_half_width(0.5, 0.25, 40, simulations=1000)
    assert result == simulate_half_width(0.5, 0.25, 40, simulations=1000)
    assert 0.07 < result["ci90_half_width"] < 0.11
    power_main(["--simulations", "30"])
    output = capsys.readouterr().out
    assert "90% half-width" in output
    assert len(output.splitlines()) == 10
