"""Deterministic offline policies; reference programs never enter observations."""

from atoms_mul.kernel import Call, Def, Lit, format_def, parse_program

from .scripted import FlakyPolicy, ScriptedPolicy

HELPER = "op rep(n: Nat, x: Nat) -> Nat = if is_zero(n) then 0 else add(x, rep(pred(n), x))"


def _unroll(node):
    if isinstance(node, Call):
        if node.name == "mul":
            count, value = node.args
            if isinstance(count, Lit):
                result = Lit(0)
                for _ in range(count.value):
                    result = Call("add", (value, result))
                return _unroll(result)
            return Call("add", (_unroll(count), _unroll(value)))
        return Call(node.name, tuple(_unroll(arg) for arg in node.args))
    return node


def _unroll_reference(reference):
    definition = parse_program(reference).defs[0]
    return format_def(Def(definition.name, definition.params, _unroll(definition.body),
                          definition.param_sorts, definition.result_sort))


class Inventor(ScriptedPolicy):
    name = "inventor"

    def act(self, observation):
        task = self.tasks[observation["task_id"]]
        reference = task["reference_aml"]
        if self.group == "A":
            return reference
        if "op rep(" in observation["library"]:
            return reference.replace("mul(", "rep(")
        if task["family"] == "constant_scale":
            return _unroll_reference(reference)
        return (HELPER + "\n" + reference.replace("mul(", "rep(")
                + ("\nsave rep" if observation["library_enabled"] else ""))


class NoSave(Inventor):
    name = "nosave"

    def act(self, observation):
        reference = self.tasks[observation["task_id"]]["reference_aml"]
        if self.group == "A":
            return reference
        return HELPER + "\n" + reference.replace("mul(", "rep(")


class Unroll(ScriptedPolicy):
    name = "unroll"

    def act(self, observation):
        task = self.tasks[observation["task_id"]]
        if self.group == "A":
            return task["reference_aml"]
        return _unroll_reference(task["reference_aml"])


class Flaky(FlakyPolicy, Inventor):
    def bad_syntax(self, observation):
        return "op solve( ="

    def bad_check(self, observation):
        params = ", ".join(f"{name}: Nat" for name in observation["task"]["params"])
        return f"op solve({params}) -> Nat = missing(0)"


POLICIES = {policy.name: policy for policy in (Inventor, NoSave, Unroll, Flaky)}
