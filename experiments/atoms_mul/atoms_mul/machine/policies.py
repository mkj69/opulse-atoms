"""Deterministic MASM baseline policies."""

from atoms_mul.harness.scripted import FlakyPolicy, ScriptedPolicy

HELPER = """sub MUL:
  set r0, 0
LOOP:
  jz r2, DONE
  add r0, r1
  dec r2
  jmp LOOP
DONE:
  halt
end"""


class Inventor(ScriptedPolicy):
    name = "inventor"

    def act(self, observation):
        task = self.tasks[observation["task_id"]]
        if self.group == "A":
            return task["reference_masm"]
        if task["family"] == "constant_scale":
            lines = ["set r0, 0"] + ["add r0, r1"] * task["k"]
            return "sub main:\n" + "\n".join("  " + line for line in lines) + "\nend"
        reference = task["reference_masm"].replace("  mul", "  call MUL")
        if "sub MUL:" in observation["library"]:
            return reference
        return (HELPER + "\n" + reference +
                ("\nsave MUL" if self.group == "B" else ""))


class NoSave(Inventor):
    name = "nosave"

    def act(self, observation):
        if self.group == "A":
            return super().act(observation)
        task = self.tasks[observation["task_id"]]
        if task["family"] == "constant_scale":
            return super().act(observation)
        return HELPER + "\n" + task["reference_masm"].replace("  mul", "  call MUL")


class Unroll(Inventor):
    name = "unroll"

    def act(self, observation):
        task = self.tasks[observation["task_id"]]
        if self.group == "A" or task["family"] == "constant_scale":
            return super().act(observation)
        return "sub main:\n  set r0, 0\n  add r0, r1\nend"


class Flaky(FlakyPolicy, Inventor):
    def bad_syntax(self, observation):
        return "sub main:\n  invalid\nend"

    def bad_check(self, observation):
        return "sub main:\n  call missing\nend"


POLICIES = {policy.name: policy for policy in (Inventor, NoSave, Unroll, Flaky)}
