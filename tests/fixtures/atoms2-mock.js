/* Atoms v2 mock data in the shapes of the core schema (docs/spec/atoms-v2.md, atoms-v2/0.1):
 * - Definition records (section 8): {id, name, kind, origin, layer, depends_on, spec, body,
 *   evidence: {method, scope: {domain, size, description}, seed, checks}, contract:
 *   {guarantees, may_change, keeps}, cost: {length, steps: {min, max, mean, over, example},
 *   reuse}, status}. `world` is added for the mock library only.
 * - Node JSON (section 6.1): {"node": "<Class>", ...fields}; given atoms have body {host: rule}.
 * - Values (opulse.value/2): {t: "int", v} | {t: "str", v} | {t: sort, tag, f: [values]}.
 * - Outcomes: {ok: value} | {bottom: reason} | {unknown: resource}.
 * - Boundary (section 10): {depth, open_names, keep_names, open_paths, kinds}.
 * Examples follow the atoms design: mul from add, Three = succ(succ(succ(Zero))), fraction, twice, fold,
 * ?front_free, ?red_streak, Hour, and an 8-bit machine program.
 *
 * Kernel trace trees and measured runs are loaded exclusively from data.js. */
(function (root) {
  "use strict";
  var A2 = root.A2 || (root.A2 = {});

  /* Values. */
  function I(n) { return { t: "int", v: n }; }
  function S(s) { return { t: "str", v: s }; }
  function card(sort, tag, f) { return { t: sort, tag: tag, f: f || [] }; }
  function B(b) { return card("bool", b ? "true" : "false"); }
  function frac(num, den) { return card("fraction", "fraction", [I(num), I(den)]); }
  function list(xs) {
    var out = card("list[int]", "nil");
    for (var i = xs.length - 1; i >= 0; i--) out = card("list[int]", "cons", [I(xs[i]), out]);
    return out;
  }

  /* Nodes. */
  function V(name) { return { node: "Var", name: name }; }
  function L(value) { return { node: "Lit", value: value }; }
  function C(fn) { return { node: "Call", fn: fn, args: [].slice.call(arguments, 1) }; }
  function T(expr) { return { node: "Test", expr: expr }; }
  function NOT(x) { return { node: "Not", operand: x }; }
  function AND(a, b) { return { node: "And", left: a, right: b }; }
  function CASE(arms, dflt) { return { node: "Case", arms: arms, default: dflt || null }; }
  function host(rule) { return { host: rule }; }

  /* Field names per sort and tag, used to label card fields (values carry none). */
  var sorts = {
    bool: { false: [], true: [] },
    fraction: { fraction: ["num", "den"] },
    "list[int]": { nil: [], cons: ["head", "tail"] },
    reg: { r0: [], r1: [], r2: [], r3: [] },
    machine_state: { machine: ["regs", "mem", "zero", "carry"] },
    robot_state: { robot: ["map", "pos", "facing", "hand"] },
  };
  var sealedSorts = { fraction: true, robot_state: true };

  function scope(domain, size, description) { return { domain: domain, size: size, description: description }; }
  function steps(min, max, mean, example) { return { min: min, max: max, mean: mean, over: "verification scope", example: example || null }; }
  function op(inputs, output, role, rule, errors) {
    return { role: role, inputs: inputs.map(function (s) { return { sort: s, enter: "bottom" }; }),
      output: { sort: output, enter: "bottom" }, rule: rule, errors: errors || [], cost: 1 };
  }

  function given(world, kind, name, spec, extra) {
    return Object.assign({ id: world + "@2/" + name, world: world, name: name, kind: kind, origin: "given", layer: 0,
      depends_on: [], spec: spec || {}, body: host(spec && spec.rule ? spec.rule : name), evidence: null,
      contract: null, cost: { length: 1, steps: steps(1, 1, 1), reuse: 0 }, status: "promoted" }, extra || {});
  }
  function invented(world, kind, name, layer, extra) {
    return Object.assign({ id: world + "@2/" + name, world: world, name: name, kind: kind, origin: "invented",
      layer: layer, depends_on: [], spec: {}, contract: null }, extra);
  }

  var defs = [
    /* Integer world, layer 0. */
    given("integer", "object", "int", { form: "given", rule: "whole numbers", sealed: false, interface: [] }),
    given("integer", "object", "zero", { form: "constant", sort: "int", rule: "the number 0" }),
    given("integer", "operation", "succ", op(["int"], "int", "transform", "a + 1"), { symbol: "+" }),
    given("integer", "operation", "dec", op(["int"], "int", "transform", "a - 1"), { symbol: "-" }),
    given("integer", "operation", "neg", op(["int"], "int", "transform", "-a"), { symbol: "-" }),
    given("integer", "operation", "is_zero", op(["int"], "bool", "decide", "a = 0")),
    given("integer", "operation", "add", op(["int", "int"], "int", "combine", "a + b"), { symbol: "+" }),
    given("integer", "operation", "mod", op(["int", "int"], "int", "combine", "a mod b", ["div_zero"]), { symbol: "%" }),
    invented("integer", "law", "#mul_comm", 2, { depends_on: ["mul"],
      spec: { statement: "eq(mul(a, b), mul(b, a)) for a: Int, b: Int", scope: "a, b in 0..15" },
      evidence: { method: "bounded", scope: scope("a, b in 0..15", 256, "proposed finite check") }, status: "written" }),
    invented("integer", "law", "#gcd_lin", 3, { depends_on: ["gcd", "mul", "add"],
      spec: { statement: "eq(gcd(a, b), gcd(add(a, mul(k, b)), b))", scope: "a, b, k in 0..15" },
      evidence: { method: "bounded", scope: scope("a, b, k in 0..15", 4096, "proposed finite check") }, status: "written" }),
    invented("integer", "bridge", "~to_frac", 4, { depends_on: ["Frac"],
      spec: { source: "Pair<Int, Int>", target: "Frac", domain: "den != 0", commuting: "Compare pair addition with Frac addition for pairs in -6..6 with nonzero denominator." },
      evidence: { method: "bounded", scope: scope("valid pairs with entries in -6..6", 156, "proposed commuting check") }, status: "written" }),
    given("integer", "combinator", "Call", { rule: "do one operation" }),
    given("integer", "combinator", "Let", { rule: "name a value, then use it" }),
    given("integer", "combinator", "Case", { rule: "the first condition that holds chooses the branch" }),
    given("integer", "combinator", "Rec", { rule: "a recursive function with a decreasing measure" }),
    given("integer", "observation", "io", { rule: "the learner sees the inputs and the result", reads: [] }),
    given("lists", "object", "List", { form: "compose", forms: { nil: [], cons: [["head", "Int"], ["tail", "List<Int>"]] }, rule: "finite lists of integers" }),
    given("lists", "operation", "add", op(["Int", "Int"], "Int", "combine", "integer addition")),
    given("lists", "operation", "mul", op(["Int", "Int"], "Int", "combine", "integer multiplication")),
    given("lists", "combinator", "Call", { rule: "apply an operation to values" }),
    given("lists", "combinator", "Case", { rule: "select the first matching arm" }),
    given("lists", "combinator", "Rec", { rule: "recurse on the list tail" }),
    given("lists", "operation", "head", op(["List<Int>"], "Int", "transform", "first item", ["invalid"])),
    given("lists", "operation", "tail", op(["List<Int>"], "List<Int>", "transform", "all items but the first")),
    given("lists", "operation", "is_nil", op(["List<Int>"], "Bool", "decide", "the list is empty")),

    /* Integer world, invented. */
    invented("integer", "object", "three", 1, { depends_on: ["zero", "succ"],
      spec: { form: "constant", sort: "int", unfold: "three = succ(succ(succ(zero)))" },
      body: C("succ", C("succ", C("succ", V("zero")))),
      evidence: { method: "exhaustive", scope: scope("closed term", 1, "the single value"), seed: null, checks: ["unfold_equivalence"] },
      contract: { guarantees: "three = 3", may_change: [], keeps: [] },
      cost: { length: 4, steps: steps(4, 4, 4, { call: "three", steps: 4 }), reuse: 2 }, status: "promoted" }),
    invented("integer", "operation", "mul", 1, { depends_on: ["add", "dec", "is_zero"],
      spec: Object.assign(op(["int", "int"], "int", "combine", "a  *  b by repeated addition"), { params: ["a", "b"], measure: "b" }),
      body: CASE([[T(C("is_zero", V("b"))), L(I(0))]], C("add", V("a"), C("mul", V("a"), C("dec", V("b"))))),
      evidence: { method: "exhaustive", scope: scope("a, b in 0..15", 256, "all 256 pairs"), seed: null, checks: ["reference", "unfold_equivalence"] },
      contract: { guarantees: "mul(a, b) = a  *  b", may_change: [], keeps: ["everything else"] },
      cost: { length: 9, steps: steps(1, 46, 23.5, { call: "mul(3, 4)", steps: 13 }), reuse: 3 }, status: "promoted" }),
    invented("lists", "operation", "dot", 2, { depends_on: ["mul", "add", "head", "tail"],
      spec: Object.assign(op(["list[int]", "list[int]"], "int", "combine", "add(mul(x1, y1), mul(x2, y2))"), { params: ["x", "y"] }),
      body: C("add", C("mul", C("head", V("x")), C("head", V("y"))), C("mul", C("head", C("tail", V("x"))), C("head", C("tail", V("y"))))),
      evidence: { method: "bounded", scope: scope("lists of length 2, entries 0..6", 2401, "every pair of length-2 lists"), seed: null, checks: ["reference", "unfold_equivalence"] },
      contract: { guarantees: "dot(x, y) = add(mul(x1, y1), mul(x2, y2))", may_change: [], keeps: ["everything else"] },
      cost: { length: 11, steps: steps(5, 41, 23, { call: "dot([1, 2], [3, 4])", steps: 30 }), reuse: 0 }, status: "promoted" }),
    invented("integer", "operation", "gcd", 2, { depends_on: ["mod", "is_zero"],
      spec: Object.assign(op(["int", "int"], "int", "combine", "greatest common divisor"), { params: ["a", "b"], measure: "b" }),
      body: CASE([[T(C("is_zero", V("b"))), V("a")]], C("gcd", V("b"), C("mod", V("a"), V("b")))),
      evidence: { method: "exhaustive", scope: scope("a, b in 0..63", 4096, "all pairs"), seed: null, checks: ["reference", "unfold_equivalence"] },
      contract: { guarantees: "gcd(a, b) divides a and b and is the largest such", may_change: [], keeps: [] },
      cost: { length: 8, steps: steps(1, 19, 7.1, { call: "gcd(4, 2)", steps: 4 }), reuse: 2 }, status: "promoted" }),
    invented("integer", "operation", "is_even", 2, { depends_on: ["is_zero", "dec"],
      spec: Object.assign(op(["int"], "bool", "decide", "a is even"), { params: ["a"], measure: "a" }),
      body: CASE([[T(C("is_zero", V("a"))), L(B(true))], [T(C("is_zero", C("dec", V("a")))), L(B(false))]], C("is_even", C("dec", C("dec", V("a"))))),
      evidence: { method: "exhaustive", scope: scope("a in 0..255", 256, "every input"), seed: null, checks: ["reference", "unfold_equivalence"] },
      cost: { length: 11, steps: steps(1, 384, 192, { call: "is_even(6)", steps: 10 }), reuse: 1 }, status: "verified" }),
    invented("integer", "combinator", "twice", 1, { depends_on: ["Call"],
      spec: { op_params: [{ name: "f", type: "A  ->  A" }], params: [{ name: "x", sort: "A" }], unfold: "twice(f, x)  ->  f(f(x))" },
      body: C("f", C("f", V("x"))),
      evidence: { method: "sampled", scope: scope("f in {succ, dec, triple}; x in -8..8", 51, "51 seeded cases"), seed: 7, checks: ["unfold_equivalence"] },
      contract: { guarantees: "types hold for every f; behaviour checked only for the sampled f", may_change: [], keeps: [] },
      cost: { length: 4, steps: steps(2, 28, 9.3, { call: "twice(succ, 5)", steps: 2 }), reuse: 4 }, status: "verified" }),
    invented("lists", "combinator", "fold", 1, { depends_on: ["Case", "Rec", "Call", "is_nil", "head", "tail"],
      spec: { op_params: [{ name: "f", type: "A  *  B  ->  B" }], params: [{ name: "z", sort: "B" }, { name: "xs", sort: "list[A]" }],
        unfold: "fold(f, z, nil)  ->  z; fold(f, z, cons(h, t))  ->  f(h, fold(f, z, t))", measure: "length(xs)" },
      body: CASE([[T(C("is_nil", V("xs"))), V("z")]], C("f", C("head", V("xs")), C("fold", V("f"), V("z"), C("tail", V("xs"))))),
      evidence: { method: "bounded", scope: scope("f in {add, mul}; lists of length 0..4, entries 0..5", 3110, "every list in the bound for each f"), seed: null, checks: ["unfold_equivalence"] },
      cost: { length: 12, steps: steps(0, 4, 2, { call: "fold(add, 0, [1, 2, 3])", steps: 3 }), reuse: 1 }, status: "verified" }),
    invented("integer", "operation", "triple", 2, { depends_on: ["mul", "three"],
      spec: Object.assign(op(["int"], "int", "transform", "3  *  x"), { params: ["x"] }),
      body: C("mul", V("x"), V("three")),
      evidence: { method: "exhaustive", scope: scope("x in 0..85", 86, "every input"), seed: null, checks: ["reference", "unfold_equivalence"] },
      cost: { length: 3, steps: steps(14, 14, 14, { call: "triple(1)", steps: 14 }), reuse: 2 }, status: "promoted" }),
    invented("integer", "object", "Quot", 2, { depends_on: ["int"],
      spec: { form: "refine", template: true, parameters: ["T", "canon"], base: "T", canon: "canon", family: "Pair<Int, Int> with reduce; Int with mod12" },
      evidence: { method: "bounded", scope: scope("two proposed instantiations", 2, "family illustration only") }, status: "written" }),

    /* Fractions (object, layer 3) and fraction addition (operation, layer 4). */
    invented("integer", "object", "fraction", 3, { depends_on: ["Int", "gcd", "neg", "mul", "Quot"],
      spec: { form: "refine", base: { record: { num: "Int", den: "Int" } }, valid: "den != 0", instantiation: "Quot[Pair<Int, Int>, reduce]",
        canon: "divide both by their gcd; make den positive", sealed: true,
        interface: ["make_fraction", "num", "den", "fraction_eq"], params: [], equality: "canonical", canon_cost: "counted" },
      body: null,
      evidence: { method: "bounded", scope: scope("num, den in -6..6", 156, "every valid representation"), seed: null,
        checks: ["canon_total", "canon_idempotent", "canon_keeps_valid", "interface_respects_canon"] },
      contract: { guarantees: "equal fractions have one canonical form", may_change: [], keeps: [] },
      cost: { length: 14, steps: steps(1, 12, 5.2, { call: "make_fraction(2, 4)", steps: 6 }), reuse: 2 }, status: "promoted" }),
    invented("integer", "operation", "frac_add", 4, { depends_on: ["fraction", "mul", "add"],
      spec: Object.assign(op(["fraction", "fraction"], "fraction", "combine", "p + q"), { params: ["p", "q"] }),
      body: C("make_fraction", C("add", C("mul", C("num", V("p")), C("den", V("q"))), C("mul", C("num", V("q")), C("den", V("p")))), C("mul", C("den", V("p")), C("den", V("q")))),
      evidence: { method: "bounded", scope: scope("num, den in -4..4", 5184, "every pair of valid fractions"), seed: null, checks: ["reference", "unfold_equivalence"] },
      cost: { length: 15, steps: steps(9, 60, 31, { call: "1/2 + 1/3", steps: 40 }), reuse: 0 }, status: "verified" }),

    /* Clock world, version 2: a true clock. */
    given("clock", "object", "hour", { form: "refine", base: "int", valid: "0 <= n <= 11", canon: "n mod 12", sealed: false, canon_cost: "free", rule: "n mod 12 on entry" }),
    invented("clock", "object", "Hour", 3, { depends_on: ["Quot"],
      spec: { form: "refine", base: "Int", canon: "mod12", instantiation: "Quot[Int, mod12]" },
      evidence: { method: "bounded", scope: scope("entries in -24..24", 49, "proposed clock range") }, status: "written" }),
    given("clock", "operation", "add", { role: "combine", inputs: [{ sort: "hour", enter: "normalize" }, { sort: "hour", enter: "normalize" }], output: { sort: "hour", enter: "normalize" }, rule: "(a + b) mod 12", errors: [], cost: 1 }),

    /* Robot world. */
    given("robot", "object", "robot_state", { form: "compose", forms: { robot: [["map", "grid"], ["pos", "cell"], ["facing", "direction"], ["hand", "item"]] }, sealed: true, rule: "the whole world" }),
    given("robot", "operation", "forward", Object.assign(op(["robot_state"], "robot_state", "act", "move one cell ahead", ["blocked"]), { changes_state: true })),
    given("robot", "operation", "turn_left", Object.assign(op(["robot_state"], "robot_state", "act", "turn 90 degrees left"), { changes_state: true })),
    given("robot", "operation", "turn_right", Object.assign(op(["robot_state"], "robot_state", "act", "turn 90 degrees right"), { changes_state: true })),
    given("robot", "operation", "eq", op(["colour", "colour"], "bool", "decide", "a = b")),
    given("robot", "operation", "succ", op(["int"], "int", "transform", "a + 1")),
    given("robot", "observation", "front_wall", { sort: "bool", reads: [], reveals: ["whether the cell in front is a wall"], rule: "is the cell in front a wall?" }),
    given("robot", "observation", "front_water", { sort: "bool", reads: [], reveals: ["whether the cell in front is water"], rule: "is the cell in front water?" }),
    given("robot", "observation", "cell_colour", { sort: "colour", reads: [], reveals: ["the colour of the current cell"], rule: "colour of the current cell" }),
    invented("robot", "observation", "front_free", 1, { depends_on: ["front_wall", "front_water"],
      spec: { reads: ["front_wall", "front_water"], memory: null, sort: "bool" },
      body: AND(NOT(T(V("front_wall"))), NOT(T(V("front_water")))),
      evidence: { method: "exhaustive", scope: scope("all probe pairs", 4, "both probes, both values"), seed: null, checks: ["reads_only_granted", "reference"] },
      cost: { length: 5, steps: steps(2, 2, 2, { call: "front_free", steps: 2 }), reuse: 5 }, status: "promoted" }),
    invented("robot", "observation", "red_streak", 1, { depends_on: ["cell_colour", "eq", "succ"],
      spec: { reads: ["cell_colour"], sort: "int",
        memory: { sort: "int", init: L(I(0)), step: CASE([[T(C("eq", V("cell_colour"), L(S("R")))), C("succ", V("memory"))]], L(I(0))) } },
      body: V("memory"),
      evidence: { method: "bounded", scope: scope("colour histories of length <= 6", 55986, "every history in the bound"), seed: null, checks: ["reads_only_granted", "reference"] },
      cost: { length: 7, steps: steps(1, 2, 1.5, null), reuse: 0 }, status: "verified" }),

    /* 8-bit machine (computer world v1, Harvard style). */
    given("machine", "object", "byte", { form: "refine", base: "int", valid: "0 <= x < 256", rule: "0..255" }),
    given("machine", "object", "reg", { form: "compose", forms: { r0: [], r1: [], r2: [], r3: [] }, rule: "register names" }),
    given("machine", "object", "machine_state", { form: "compose", forms: { machine: [["regs", "array[4, byte]"], ["mem", "array[256, byte]"], ["zero", "flag"], ["carry", "flag"]] }, rule: "registers, memory and flags" }),
    given("machine", "operation", "add", op(["byte", "byte"], "byte", "combine", "(a + b) mod 256; sets carry")),
    given("machine", "operation", "dec", op(["byte"], "byte", "transform", "(a - 1) mod 256")),
    given("machine", "operation", "is_zero", op(["byte"], "bool", "decide", "a = 0")),
    given("machine", "combinator", "Blocks", { rule: "labelled blocks with a program counter" }),
    given("machine", "combinator", "Jump", { rule: "go to a label, or go to one of two labels on a condition" }),
    invented("machine", "operation", "mul_byte", 1, { depends_on: ["add", "dec", "is_zero", "Blocks", "Jump"],
      spec: Object.assign(op(["byte", "byte"], "byte", "combine", "r0 := r1  *  r2 mod 256"), { params: ["r1", "r2"] }),
      body: { node: "Blocks", vars: [["r0", L(I(0))]], entry: "loop", blocks: [
        ["loop", { assigns: [], end: { node: "CondJump", cond: T(C("is_zero", V("r2"))), then: "done", else_: "body" } }],
        ["body", { assigns: [["r0", C("add", V("r0"), V("r1"))], ["r2", C("dec", V("r2"))]], end: { node: "Jump", target: "loop" } }],
        ["done", { assigns: [], end: { node: "Halt", value: V("r0") } }],
      ] },
      evidence: { method: "exhaustive", scope: scope("byte  *  byte", 65536, "all 8-bit pairs, full machine state"), seed: null, checks: ["reference", "unfold_equivalence"] },
      contract: { guarantees: "r0 = r1  *  r2 mod 256", may_change: ["r2", "carry"], keeps: ["r1", "r3", "memory"] },
      cost: { length: 14, steps: steps(2, 1277, 639.5, { call: "mul_byte(3, 4)", steps: 22 }), reuse: 1 }, status: "promoted" }),
  ];

  function asciiName(name, kind) {
    if (kind === "object") return ({ int: "Int", zero: "Zero", three: "Three", fraction: "Frac", hour: "ClockHour",
      byte: "Byte", reg: "Reg", machine_state: "MachineState", robot_state: "RobotState" })[name] || name;
    if (kind === "combinator") return name.charAt(0) === "@" ? name : "@" + name;
    if (kind === "observation") return name.charAt(0) === "?" ? name : "?" + name;
    return name;
  }
  defs.forEach(function (def) { def.name = asciiName(def.name, def.kind); });
  defs.forEach(function (def) {
    def.depends_on = (def.depends_on || []).map(function (name) {
      var dependency = defs.filter(function (candidate) { return candidate.world === def.world && (candidate.name === name || asciiName(name, candidate.kind) === candidate.name); })[0];
      return dependency ? dependency.name : name;
    });
  });
  var legacyNames = { Int: "int", Zero: "zero", Three: "three", Frac: "fraction", ClockHour: "hour",
    Byte: "byte", Reg: "reg", MachineState: "machine_state", RobotState: "robot_state", mul_byte: "MUL",
    "@twice": "twice", "@fold": "fold", "@Call": "Call", "@Let": "Let", "@Case": "Case", "@Rec": "Rec",
    "@Blocks": "Blocks", "@Jump": "Jump", "?io": "io", "?front_wall": "front_wall", "?front_water": "front_water",
    "?cell_colour": "cell_colour", "?front_free": "front_free", "?red_streak": "red_streak" };
  defs.slice().forEach(function (def) {
    if (legacyNames[def.name]) defs.push(Object.assign({}, def, { name: legacyNames[def.name], legacy: true }));
  });

  /* Layer-0 steps charged by a kernel trace: its given-atom leaves. */

  var derivations = A2.kernelData ? A2.kernelData.derivations : {};

  /* ---- Worlds: layer-0 declarations (opulse.world/2, abridged) ------------- */
  function layer0(world) {
    return defs.filter(function (def) { return def.world === world && def.layer === 0 && !def.legacy; });
  }
  var worlds = {
    integer: { world: "integer", version: 2, title: "Integers", dialect: "atoms-v2",
      combinators: { nodes: ["Var", "Lit", "Call", "Let", "Case", "Rec"] },
      observation: { truth: null, show: { input: "values", result: "value" }, judge_view: "full_state" } },
    lists: { world: "lists", version: 2, title: "Lists", dialect: "atoms-v2",
      combinators: { nodes: ["Var", "Lit", "Call", "Let", "Case", "Rec"] },
      observation: { truth: null, show: { input: "values", result: "value" }, judge_view: "full_state" } },
    clock: { world: "clock", version: 2, title: "Clock", dialect: "atoms-v2",
      combinators: { nodes: ["Var", "Lit", "Call", "Let", "Case", "Rec"] },
      observation: { truth: null, show: { input: "values", result: "value" }, judge_view: "full_state" } },
    robot: { world: "robot", version: 2, title: "Robot", dialect: "atoms-v2",
      combinators: { nodes: ["Var", "Lit", "Call", "Let", "Case", "Rec"] },
      observation: { truth: "robot_state", probes: ["front_wall", "front_water", "cell_colour"],
        capabilities: { learner: { channels: ["results", "errors", "renders", "traces", "steps", "memory"], probes: "all" } },
        show: { input: "probes", result: "probes" }, judge_view: "full_state" },
      grid: ["#######", "#..~..#", "#.R.#.#", "#..~R.#", "#######"],
      robot: { x: 1, y: 1, facing: "E" },
      legend: { "#": "wall", "~": "water", ".": "floor", R: "red floor" } },
    machine: { world: "machine", version: 1, title: "8-bit machine", dialect: "atoms-v2",
      combinators: { nodes: ["Var", "Lit", "Call", "Blocks", "Jump", "CondJump", "Halt"] },
      observation: { truth: "machine_state", show: { input: "registers", result: "r0" }, judge_view: "full_state" } },
  };

  /* ---- Object scenes -------------------------------------------------------- */
  var objects = {
    fraction: { inputs: [2, 4], invalid: { inputs: [3, 0], outcome: { bottom: "invalid" }, gloss: "den = 0" },
      equal: { left: frac(2, 4), right: frac(1, 2), canon: frac(1, 2) } },
    hour: { enter: 14, canon: 2, dial: 12 },
    list: { items: [1, 2, 3], value: list([1, 2, 3]) },
  };

  /* Short glosses for Bottom reasons (core identifiers). */
  var reasons = { div_zero: "division by zero", blocked: "the move is blocked", no_branch: "no case arm matched",
    invalid: "the value is not valid", measure: "the measure did not decrease", overflow: "out of range",
    nan_condition: "a condition failed" };

  A2.sorts = sorts;
  A2.sealedSorts = sealedSorts;
  A2.mock = {
    defs: defs,
    find: function (name, world) {
      return defs.filter(function (def) { return (def.name === name || def.name.replace(/^[@?]/, "") === name ||
        asciiName(name, def.kind) === def.name) && (!world || def.world === world); })[0] || null;
    },
    layer0: layer0,
    worlds: worlds,
    derivations: derivations,
    charged: A2.chargedLeaves,
    objects: objects,
    reasons: reasons,
    build: { I: I, S: S, B: B, card: card, frac: frac, list: list, V: V, L: L, C: C, T: T },
  };
  if (typeof module !== "undefined" && module.exports && !A2.kernelData) require("../../docs/assets/js/atoms2/data.js");
  if (typeof module !== "undefined" && module.exports) module.exports = A2.mock;
})(typeof window !== "undefined" ? window : globalThis);
