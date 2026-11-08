"""Opt-in OpenAI-compatible chat policy; importing this module never contacts an API."""

import json
import os
import re
import urllib.request

DEFAULT_MAX_OUTPUT_TOKENS = 1024


def extract_program(reply):
    """Return the first fenced program, or the entire unfenced response."""
    match = re.search(r"```[^\r\n]*\r?\n(.*?)\r?\n?```",
                      reply, re.IGNORECASE | re.DOTALL)
    return (match.group(1) if match else reply).strip()


class LLMPolicy:
    name = "llm"

    def __init__(self, *, allow_api=False, base_url=None, model=None, api_key_env="OPENAI_API_KEY",
                 temperature=0.7, max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS):
        if not allow_api:
            raise RuntimeError("LLMPolicy requires explicit allow_api=True")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL")
        self.api_key_env = api_key_env
        self.api_key = os.environ.get(api_key_env)
        if not self.api_key:
            raise RuntimeError(f"Missing API key in {api_key_env}")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        if not self.model:
            raise ValueError("Model must be supplied via model or OPENAI_MODEL")

    def reset(self, *, group, episode, seed):
        self.group = group
        self.episode = episode
        self.seed = seed

    def act(self, observation):
        # The rendered prompt already contains the feedback of earlier attempts.
        messages = [{"role": "user", "content": observation["prompt"]}]
        body = {"model": self.model, "messages": messages, "temperature": self.temperature,
                "max_tokens": self.max_output_tokens}
        if getattr(self, "seed", None) is not None:
            body["seed"] = self.seed
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST")
        for retry in range(3):  # PREREG: an API error is retried up to 3 times
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    answer = json.load(response)
                return extract_program(answer["choices"][0]["message"]["content"])
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                if retry == 2:
                    raise
