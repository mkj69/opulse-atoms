"""ASCII atoms-v2 declaration; executable host semantics live in machine.py."""

TAGS = {
    "domain": "program", "modalities": ["text"],
    "open_kinds": ["object", "operation", "combinator", "observation"],
    "star_kind": "combinator", "reasoning": ["compute", "search", "equivalence", "inference"],
    "state": "stateful", "outcomes": "deterministic", "visibility": "full", "agents": 1,
    "scale": "32 registers, 64 KiB unified byte memory, 11 invented definitions, up to 10000 executed instructions",
    "difficulty": "one instruction through ABI-correct nested control flow and program synthesis",
    "uses": ["rl-training", "evaluation", "teaching"],
}

WORLD = {
    "schema": "opulse.world/2", "world": "riscv-rv32i", "version": 1, "dialect": "atoms-v2",
    "tags": TAGS, "open_kinds": TAGS["open_kinds"],
    "params": {"word_bits": 32, "ram_bytes": 65536},
    "constants": {"registers": 32, "return_pc": 0x1000},
    "objects": [
        {"name": name, "form": "given"} for name in
        ("Nat", "Bool", "Byte", "Word", "Reg", "Memory", "Instruction", "Fields", "TraceEvent", "Machine")
    ],
    "operations": [
        {"name": "decode", "role": "transform", "inputs": [{"sort": "Instruction"}],
         "output": {"sort": "Fields"}, "rule": "Decode RV32I bitfields"},
        {"name": "execute", "role": "transform", "inputs": [{"sort": "Machine"}],
         "output": {"sort": "Machine"}, "rule": "Execute one RV32I instruction"},
        {"name": "encode", "role": "transform", "inputs": [{"sort": "Fields"}],
         "output": {"sort": "Instruction"}, "rule": "Encode supported RV32I fields"},
        {"name": "identity_word", "role": "transform", "inputs": [{"sort": "Word"}],
         "output": {"sort": "Word"}, "rule": "Preserve a 32-bit register word"},
    ],
    "combinators": {"nodes": ["Var", "Lit", "Call", "Case", "Rec"],
                    "library": ["seq", "branch", "loop", "call"], "recursion": "fuel"},
    "observation": {"truth": "Machine", "judge_view": "full_state", "probes": [
                    {"name": name, "sort": result, "reveals": [name]}
                    for name, result in (("reg", "Word"), ("mem", "Word"),
                                         ("pc", "Word"), ("trace", "TraceEvent"))],
                    "capabilities": {"learner": {"channels": ["results", "errors", "traces", "steps"],
                                                  "probes": "all"}}},
    "lock": {},
}
WORLD["layer0"] = {
    "objects": [record["name"] for record in WORLD["objects"]],
    "operations": [record["name"] for record in WORLD["operations"]],
    "combinators": WORLD["combinators"]["library"],
    "observations": [record["name"] for record in WORLD["observation"]["probes"]],
}

_STORY_PLAN = (
    ("object", "WrappedWord", "Wrap a machine word in a tagged object."),
    ("operation", "step_once", "Delegate one instruction to the given execute operation."),
    ("observation", "machine_state", "Observe the entire machine without changing it."),
    ("combinator", "step_block", "Apply one execution step through a combinator."),
    ("operation", "advance_machine", "Expose one machine step as a derived operation."),
    ("object", "FrameWord", "Wrap a stack word in a tagged object."),
    ("combinator", "step_branch", "Step a machine whose next instruction may branch."),
    ("observation", "observed_machine", "Observe a machine without changing its state."),
    ("operation", "step_after", "Execute one instruction on a supplied machine."),
    ("combinator", "step_loop", "Apply a single loop-body execution step."),
    ("combinator", "step_call", "Apply a single call/return execution step."),
)


def _story_definition(kind: str, name: str) -> dict:
    if kind == "object":
        spec = {"name": name, "form": "compose", "tags": {"value": {"word": "Word"}}}
        body = None
    elif kind == "operation":
        spec = {"name": name, "role": "transform", "inputs": [{"sort": "Machine"}],
                "output": {"sort": "Machine"}, "rule": "One RV32I step", "input_names": ["m"]}
        body = {"node": "Call", "fn": "execute", "args": [{"node": "Var", "name": "m"}]}
    elif kind == "combinator":
        spec = {"name": name, "params": ["m"], "op_params": [],
                "body": {"node": "Call", "fn": "execute", "args": [{"node": "Var", "name": "m"}]}}
        body = spec["body"]
    else:
        spec = {"name": name, "reads": ["Machine"], "body": {"node": "Var", "name": "s"}}
        body = spec["body"]
    return {"schema": "opulse.definition/2", "name": name, "kind": kind,
            "origin": "invented", "layer": 1, "depends_on": ["execute"] if
            kind in ("operation", "combinator") else [], "spec": spec, "body": body,
            "status": "written"}


STORY = [{"curriculum_stage": layer, "kind": kind, "purpose": purpose,
          "definition": _story_definition(kind, name)}
         for layer, (kind, name, purpose) in enumerate(_STORY_PLAN, 1)]
WORLD["story"] = STORY

LADDER = [
    {"level": 1, "skill": "decode one published instruction word and execute it", "fuel": 1},
    {"level": 2, "skill": "signed versus unsigned branches, byte loads and wraparound", "fuel": 12},
    {"level": 3, "skill": "PC-relative loops and little-endian memory aliasing", "fuel": 100},
    {"level": 4, "skill": "infer instructions from input/output traces and invert bounded loops", "fuel": 1000},
    {"level": 5, "skill": "synthesize ABI-preserving callable procedures with real encodings", "fuel": 10000},
]
WORLD["ladder"] = LADDER
