# Multiplication experiment analysis

From the repository root, use `PYTHONPATH=experiments/atoms_mul python -m
atoms_mul.analysis.analyze --run experiments/atoms_mul/runs/<run_id>` to write
`analysis.json` and `analysis.md`. The default is 10,000 bootstrap resamples;
`--resamples` is intended for fast synthetic tests only. Run
`python -m atoms_mul.analysis.power` to reproduce the simulated sample-size
table. The simulator uses independent normal episode-level observations with
the given mean and standard deviation; it estimates the difference of two
group means, not the behavior of an individual task.

Accuracy excludes `api_error` tasks from each episode's denominator. Episodes
without any eligible tasks for a stage have no accuracy for that stage and are
omitted from that outcome's group comparison. API errors remain counted in the
group report. Reuse uses all stage-2 tasks as its denominator for A and B; C has
no library, so its reuse is not applicable. Length adds the reported definition
sizes for all tasks, subtracting a previously saved definition's size if that
definition is repeated in a later final program. Steps and boundary steps are the
mean over correct stage-2 tasks (none: not available). If the C median is zero, a B/C median ratio is
undefined and its confidence interval is reported as unavailable.

`python -m atoms_mul.analysis.cost --prompts <prompts.jsonl>` estimates calls
from the distinct group/stage/task combinations in the dry run. Each rendered
prompt costs `ceil(characters / 4)` estimated input tokens. Expected input uses
the average available attempt prompt for each task; worst case uses the
largest available attempt prompt three times. Expected output uses
`--output-mean` tokens per call (default 300, an assumption, not an observed
count); worst case uses the per-call cap `--max-output`. Costs
appear only if both per-million-token prices are supplied.

`LLMPolicy` requires explicit `allow_api=True` and a model name from `model`
or `OPENAI_MODEL`. It reads the key from `OPENAI_API_KEY` by default (change
with `api_key_env`) and the base URL from `OPENAI_BASE_URL` by default.
