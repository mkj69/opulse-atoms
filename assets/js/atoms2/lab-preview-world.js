(function (root) {
  "use strict";
  var A2 = root.A2 || (root.A2 = {});
  if (root.N3 && A2.kernelData && A2.kernelData.notation3) root.N3.register(A2.kernelData.notation3);
  function given(world, kind, name, inputs, output) {
    return { world: world, kind: kind, name: name, origin: "given", layer: 0,
      spec: kind === "operation" ? { inputs: inputs.map(function (sort) { return { sort: sort }; }), output: { sort: output } } : { sort: output, reads: [] } };
  }
  var defs = [
    given("integer", "object", "Int", [], "int"),
    given("integer", "object", "Zero", [], "int"),
    given("integer", "operation", "succ", ["int"], "int"),
    given("integer", "operation", "dec", ["int"], "int"),
    given("integer", "operation", "neg", ["int"], "int"),
    given("integer", "operation", "is_zero", ["int"], "bool"),
    given("integer", "operation", "add", ["int", "int"], "int"),
    given("integer", "operation", "lt", ["int", "int"], "bool"),
    given("integer", "operation", "mod", ["int", "int"], "int"),
    given("robot", "observation", "front_wall", [], "bool"),
    given("robot", "observation", "front_water", [], "bool")
  ];
  ["Int", "Zero"].forEach(function (name) { defs.push(given("robot", "object", name, [], "int")); });
  [["succ", 1, "int"], ["dec", 1, "int"], ["neg", 1, "int"], ["is_zero", 1, "bool"], ["add", 2, "int"]].forEach(function (entry) {
    defs.push(given("robot", "operation", entry[0], Array(entry[1]).fill("int"), entry[2]));
  });
  function variable(name) { return { node: "Var", name: name }; }
  function call(name, args) { return { node: "Call", fn: name, args: args }; }
  defs.push({ world: "integer", kind: "operation", name: "mul", origin: "invented", layer: 1,
    spec: { inputs: [{ sort: "int" }, { sort: "int" }], output: { sort: "int" }, params: ["a", "b"] },
    body: { node: "Case", arms: [
      [{ node: "Test", expr: call("is_zero", [variable("b")]) }, { node: "Lit", value: { t: "int", v: 0 } }],
      [{ node: "Test", expr: call("lt", [variable("b"), { node: "Lit", value: { t: "int", v: 0 } }]) },
        call("neg", [call("mul", [variable("a"), call("neg", [variable("b")])])])]],
      default: call("add", [variable("a"), call("mul", [variable("a"), call("dec", [variable("b")])])]) } });
  defs.push({ world: "integer", kind: "combinator", name: "twice", origin: "invented", layer: 1,
    spec: { op_params: [{ name: "f" }], params: [{ name: "x", sort: "int" }], output: { sort: "int" } },
    body: call("f", [call("f", [variable("x")])]) });
  defs.push({ world: "robot", kind: "observation", name: "front_free", origin: "invented", layer: 1,
    spec: { reads: ["front_wall", "front_water"], sort: "bool" },
    body: { node: "And", left: { node: "Not", operand: variable("front_wall") },
      right: { node: "Not", operand: variable("front_water") } } });
  A2.mock = { defs: defs, worlds: { robot: { observation: { probes: ["front_wall", "front_water"] } } },
    find: function (name, world) { return defs.find(function (item) { return item.name === name && item.world === world; }) || null; },
    charged: A2.chargedLeaves };
  if (typeof module !== "undefined" && module.exports) module.exports = A2.mock;
})(typeof window !== "undefined" ? window : globalThis);
