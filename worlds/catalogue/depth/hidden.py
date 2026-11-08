"""Exact finite hidden-card world. Run: python3 out/hidden.py.

Receiver code receives only ReceiverView/Belief. Truth is confined to the
trusted enumerator and judge; probabilities are rational throughout.
"""

from dataclasses import dataclass
from fractions import Fraction as F
from functools import lru_cache
from itertools import product
from pathlib import Path
import json


CARDS = ("R", "B")
LAMPS = ("blue", "red")
MODES = ("B", "A")  # Tie-breaking order; stopping wins exact ties.
COST = {"A": 3, "B": 1}
RED = {"A": {"R": F(1), "B": F(1, 2)},
       "B": {"R": F(1, 4), "B": F(3, 4)}}
MAX_BUDGET = 12


def eq(left, right):
    return left == right


def lt(left, right):
    return left < right


def le(left, right):
    return left <= right


def add(left, right):
    return left + right


def mul(left, right):
    return left * right


def div(left, right):
    if right == 0:
        raise ValueError("division by zero")
    return F(left, right)


def channel(mode, card):
    """Public counterfactual law, NOT an oracle for the actual sealed card."""
    if mode not in COST or card not in CARDS:
        raise ValueError("unknown mode or card")
    red = RED[mode][card]
    return {"red": red, "blue": 1 - red}


@dataclass(frozen=True)
class Truth:
    card: str
    history: tuple = ()  # (mode, lamp) pairs

    def __post_init__(self):
        if self.card not in CARDS:
            raise ValueError("card")


@dataclass(frozen=True)
class ReceiverView:
    history: tuple
    actions: tuple = ()


def receiver(truth, actions=()):
    return ReceiverView(truth.history, tuple(actions))


def judge(truth, choice):
    if choice not in CARDS:
        raise ValueError("guess")
    return choice == truth.card


def signal(truth, mode):
    """Trusted probabilistic transition, enumerated rather than sampled."""
    return {Truth(truth.card, truth.history + ((mode, lamp),)): probability
            for lamp, probability in channel(mode, truth.card).items()
            if probability}


def guess(view, choice):
    if choice not in CARDS:
        raise ValueError("guess")
    return ReceiverView(view.history, view.actions + (choice,))


def bind(distribution, action):
    """Finite distribution bind; weights on equal outcomes are added."""
    result = {}
    for state, weight in distribution.items():
        for outcome, conditional in action(state).items():
            result[outcome] = result.get(outcome, F(0)) + weight * conditional
    return {state: weight for state, weight in result.items() if weight}


def lamps(view):
    return tuple(lamp for _, lamp in view.history)


@dataclass(frozen=True)
class Belief:
    r: F
    b: F

    def __post_init__(self):
        if self.r < 0 or self.b < 0 or self.r + self.b != 1:
            raise ValueError("belief must be a normalized finite posterior")


PRIOR = Belief(F(1, 2), F(1, 2))


def update(belief, mode, lamp):
    if lamp not in LAMPS:
        raise ValueError("lamp")
    r = mul(belief.r, channel(mode, "R")[lamp])
    b = mul(belief.b, channel(mode, "B")[lamp])
    total = add(r, b)
    if eq(total, 0):
        raise ValueError("impossible observation")
    return Belief(div(r, total), div(b, total))


def scan(belief, modes, observed, step=update):
    if len(modes) != len(observed):
        raise ValueError("unpaired modes and lamps")
    for mode, lamp in zip(modes, observed):
        belief = step(belief, mode, lamp)
    return belief


def confidence(belief):
    return max(belief.r, belief.b)


@dataclass(frozen=True)
class Leaf:
    choice: str

    def __post_init__(self):
        if self.choice not in CARDS:
            raise ValueError("choice")


@dataclass(frozen=True)
class Ask:
    mode: str
    red: object
    blue: object

    def __post_init__(self):
        if self.mode not in COST or not isinstance(self.red, (Ask, Leaf)) or not isinstance(self.blue, (Ask, Leaf)):
            raise ValueError("invalid policy node")


def branch_probability(belief, mode, lamp):
    return sum((getattr(belief, card.lower()) * channel(mode, card)[lamp]
                for card in CARDS), F(0))


def value(policy, belief, budget):
    """Exact success probability; invalid branches fail even if unreachable."""
    if not 0 <= budget <= MAX_BUDGET:
        raise ValueError("budget")
    if isinstance(policy, Leaf):
        return getattr(belief, policy.choice.lower())
    if not isinstance(policy, Ask) or COST[policy.mode] > budget:
        raise ValueError("invalid or over-budget policy")
    result = F(0)
    for lamp, child in (("red", policy.red), ("blue", policy.blue)):
        mass = branch_probability(belief, policy.mode, lamp)
        posterior = update(belief, policy.mode, lamp) if mass else belief
        child_value = value(child, posterior, budget - COST[policy.mode])
        result += mass * child_value
    return result


def best_leaf(belief):
    return Leaf("R" if belief.r >= belief.b else "B")


@lru_cache(None)
def _optimize(belief, budget):
    champion = best_leaf(belief)
    optimum = value(champion, belief, budget)
    for mode in MODES:
        if COST[mode] > budget:
            continue
        children = {}
        for lamp in ("red", "blue"):
            mass = branch_probability(belief, mode, lamp)
            children[lamp] = (_optimize(update(belief, mode, lamp), budget - COST[mode])[0]
                              if mass else Leaf("R"))
        contender = Ask(mode, children["red"], children["blue"])
        score = value(contender, belief, budget)
        if score > optimum:
            champion, optimum = contender, score
    return champion, optimum


def optimize(belief, budget, evaluator=value):
    if evaluator is not value:
        raise ValueError("unverified evaluator slot")
    if not 0 <= budget <= MAX_BUDGET:
        raise ValueError("budget")
    return _optimize(belief, budget)[0]


def first(policy):
    return policy.mode if isinstance(policy, Ask) else "guess_" + policy.choice


def regret(policy, belief, budget):
    return value(optimize(belief, budget), belief, budget) - value(policy, belief, budget)


def invert(modes, target, budget, action):
    """Lexicographically earliest attainable public trace; never reads Truth."""
    if action not in ("A", "B", "guess_R", "guess_B"):
        raise ValueError("action")
    for observed in product(LAMPS, repeat=len(modes)):
        try:
            belief = scan(PRIOR, modes, observed)
        except ValueError:
            continue
        if eq(belief.r, target) and eq(first(optimize(belief, budget)), action):
            return observed
    raise ValueError("no witness")


def fmt(number):
    return str(number)


def render_belief(belief):
    return "Belief<" + fmt(belief.r) + "," + fmt(belief.b) + ">"


def render_policy(policy):
    if isinstance(policy, Leaf):
        return "Leaf<" + policy.choice + ">"
    return "Ask<" + policy.mode + "," + render_policy(policy.red) + "," + render_policy(policy.blue) + ">"


def trace_likelihood(card, modes, observed):
    probability = F(1)
    for mode, lamp in zip(modes, observed):
        probability *= channel(mode, card)[lamp]
    return probability


def _checks():
    specification = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))
    assert specification["id"] == "hidden"
    assert eq(add(F(1, 3), F(2, 3)), 1) and eq(mul(F(3, 4), F(2, 3)), F(1, 2))
    assert eq(div(2, 6), F(1, 3)) and lt(0, F(1, 2)) and le(F(1, 2), F(1, 2))
    assert [entry["kind"] for entry in specification["tower"]].count("object") >= 2
    assert len(specification["tower"]) == 10
    initial = Truth("R")
    assert receiver(initial) == receiver(Truth("B"))
    assert all(receiver(state) == ReceiverView((("A", "red"),))
               for state in (Truth("R", (("A", "red"),)), Truth("B", (("A", "red"),))))
    assert judge(initial, "R") and not judge(Truth("B"), "R")
    assert guess(receiver(initial), "R").actions == ("R",)
    assert sum(signal(initial, "A").values()) == 1
    assert bind({initial: F(1)}, lambda state: signal(state, "A")) == signal(initial, "A")
    assert scan(PRIOR, ("A",), ("red",)) == Belief(F(2, 3), F(1, 3))
    assert value(Ask("A", Leaf("R"), Leaf("B")), PRIOR, 3) == F(3, 4)
    assert all(trace_likelihood(card, ("A", "B"), ("red", "blue")) ==
               (F(3, 4) if card == "R" else F(1, 8)) for card in CARDS)
    assert all(sum((trace_likelihood(card, ("B", "A", "B"), observed) for observed in
                    product(LAMPS, repeat=3)), F(0)) == 1 for card in CARDS)
    assert regret(optimize(PRIOR, 5), PRIOR, 5) == 0
    hist = (("A", "B", "B", "A", "B", "B"), ("red", "blue", "red", "red", "blue", "red"))
    belief = scan(PRIOR, *hist)
    invert_modes = ("B", "A", "B", "B", "A", "B", "B")
    witness_target = scan(PRIOR, invert_modes, ("blue", "red", "red", "blue", "red", "red", "blue")).r
    witness_action = first(optimize(Belief(witness_target, 1 - witness_target), 5))
    witness = invert(invert_modes, witness_target, 5, witness_action)
    decision_belief = scan(PRIOR, ("A", "B", "B"), ("red", "blue", "red"))
    candidate = Ask("B", Ask("B", Leaf("B"), Leaf("R")),
                    Ask("A", Leaf("R"), Leaf("B")))
    examples = [
        "List<" + ",".join(lamps(ReceiverView((("A", "red"), ("B", "blue"), ("B", "red"))))) + ">",
        render_belief(Belief(F(2, 3), F(1, 3))),
        render_belief(update(PRIOR, "B", "blue")),
        render_belief(belief),
        fmt(confidence(belief)),
        "Policy<" + render_policy(Ask("A", Leaf("R"), Leaf("B"))) + ">",
        fmt(value(Ask("A", Leaf("R"), Leaf("B")), PRIOR, 3)),
        fmt(value(optimize(PRIOR, 6), PRIOR, 6)),
        first(optimize(PRIOR, 6)),
        fmt(regret(candidate, decision_belief, 4)),
    ]
    assert examples == [entry["value"] for entry in specification["tower"]], (examples, [entry["value"] for entry in specification["tower"]])
    showcase = [
        "value=" + fmt(value(optimize(belief, 6), belief, 6)) + "; first=" + first(optimize(belief, 6)) + "; posterior_R=" + fmt(belief.r),
        "Lamps<" + ",".join(witness) + ">",
        "yes" if lt(regret(candidate, decision_belief, 4), F(1, 32)) else "no",
    ]
    assert showcase == [entry["answer"] for entry in specification["showcase"]], (showcase, [entry["answer"] for entry in specification["showcase"]])
    assert scan(PRIOR, invert_modes, witness).r == witness_target
    assert witness_target == F(12, 13) and witness_action == "B"
    assert first(optimize(scan(PRIOR, invert_modes, witness), 5)) == witness_action
    for earlier in product(LAMPS, repeat=len(invert_modes)):
        if earlier >= witness:
            break
        if any(trace_likelihood(card, invert_modes, earlier) for card in CARDS):
            earlier_belief = scan(PRIOR, invert_modes, earlier)
            assert earlier_belief.r != witness_target or first(optimize(earlier_belief, 5)) != witness_action
    return examples, showcase, witness_target, witness_action, witness


if __name__ == "__main__":
    print("OK") if _checks() else None
