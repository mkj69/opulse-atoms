"""Shared task lookup and retry behavior for scripted baselines."""


class ScriptedPolicy:
    name = "scripted"

    def __init__(self, tasks_stage1=(), tasks_stage2=()):
        self.tasks = {task["id"]: task for task in (*tasks_stage1, *tasks_stage2)}

    def reset(self, *, group, episode, seed):
        self.group = group

    def act(self, observation):
        raise NotImplementedError


class FlakyPolicy:
    """Fail parsing, then checking, then delegate to the track's inventor."""

    name = "flaky"

    def act(self, observation):
        if observation["attempt"] == 1:
            return self.bad_syntax(observation)
        if observation["attempt"] == 2:
            return self.bad_check(observation)
        return super().act(observation)
