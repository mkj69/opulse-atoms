(function (root) {
  "use strict";
  var api = root.OpulseWorldsDeclare = root.OpulseWorldsDeclare || {};

  function layer0(worldJson) {
    var data = worldJson || {};
    var atoms = Array.isArray(data.atoms) ? data.atoms : [];
    var types = [];
    function addType(type) {
      if (typeof type === "string" && type && types.indexOf(type) < 0) types.push(type);
    }
    atoms.forEach(function (atom) {
      (Array.isArray(atom.params) ? atom.params : []).forEach(function (param) { addType(param && param.type); });
      addType(atom.result_type);
    });
    types.sort();
    var operations = atoms.filter(function (atom) { return atom && (atom.name || atom.symbol); }).map(function (atom) {
      return { name: atom.name || atom.symbol, symbol: atom.symbol || "", signature: atom.signature || "",
        kind: "operation", origin: "given", layer: 0 };
    });
    var combinators = ["Call", "Let", "Case", "Rec"];
    if (data.world === "action") combinators.push("repeat_until");
    var observations = data.world === "action"
      ? atoms.filter(function (atom) { return atom && /^(front_|holding$|held_colour$)/.test(atom.name || ""); })
        .map(function (atom) { return atom.name; }).concat(["inputs", "result", "full-state judging"])
      : ["inputs", "result"];
    return {
      objects: types.map(function (type) { return { name: type === "state" && data.world === "action" ? "robot state" : type,
        kind: "object", origin: "given", layer: 0 }; }),
      operations: operations,
      combinators: combinators.map(function (name) { return { name: name, kind: "combinator", origin: "given", layer: 0 }; }),
      observations: observations.map(function (name) { return { name: name, kind: "observation", origin: "given", layer: 0 }; }),
      laws: [],
      bridges: []
    };
  }
  api.layer0 = layer0;

  function legend(container, A2) {
    container.classList.add("a2-worlds-declare-legend");
    container.appendChild(A2.el("span", { class: "a2-worlds-declare-legend-label", text: "SIX KINDS / LAYER 0" }));
    A2.KINDS6.forEach(function (kind) { container.appendChild(A2.kindBadge(kind)); });
  }

  function render(container, data, A2) {
    if (root.N3 && data.notation3) root.N3.register(data.notation3);
    var declaration = layer0(data);
    var card = A2.el("section", { class: "a2-worlds-declare", "aria-label": "Layer 0 declaration" });
    card.appendChild(A2.el("div", { class: "a2-worlds-declare-head" }, [
      A2.el("div", null, [A2.el("p", { class: "a2-worlds-declare-eyebrow", text: "GIVEN BY THIS WORLD" }),
        A2.el("h3", { text: "Layer 0" })]),
      A2.el("span", { class: "a2-worlds-declare-seal", text: "LEGACY-V1 / LIVE" })
    ]));
    var grid = A2.el("div", { class: "a2-worlds-declare-grid" });
    A2.KINDS6.forEach(function (kind) {
      var plural = kind === "object" ? "objects" : kind === "operation" ? "operations" : kind + "s";
      var entries = declaration[plural];
      var column = A2.el("div", { class: "a2-worlds-declare-kind a2-k-" + kind });
      column.appendChild(A2.el("div", { class: "a2-worlds-declare-kind-head" }, [
        A2.kindBadge(kind), A2.el("span", { class: "a2-worlds-declare-count", text: String(entries.length) })]));
      var chips = A2.el("div", { class: "a2-worlds-declare-chips" });
      entries.forEach(function (entry) {
        var chip = root.N3 && !root.N3.lookup(entry.name, data.world) ?
          A2.el("span", { class: "a2-worlds-declare-detail", text: "No source published" }) :
          A2.token(entry.name, { kind: entry.kind, origin: entry.origin, layer: entry.layer, world: data.world });
        if (entry.signature) chip.title = entry.name + " / " + entry.signature;
        chips.appendChild(chip);
      });
      if (!entries.length) chips.appendChild(A2.el("span", { class: "a2-worlds-declare-detail", text: "None declared" }));
      column.appendChild(chips);
      if (kind === "combinator") column.appendChild(A2.el("p", { class: "a2-worlds-declare-detail",
        text: "Substitution, branch, recursion" }));
      if (kind === "observation" && data.world === "action") column.appendChild(A2.el("p", {
        class: "a2-worlds-declare-detail", text: "Probes are visible to the learner. The judge checks full state." }));
      grid.appendChild(column);
    });
    card.appendChild(grid);
    if (root.N3 && root.N3.legendPanel && data.notation3) card.appendChild(root.N3.legendPanel(data.world));
    card.appendChild(A2.el("p", { class: "a2-worlds-declare-library", text:
      "Library: The Operators tab below contains this world's grown definitions." }));
    var decision = A2.catalog && Array.isArray(A2.catalog.current_worlds) &&
      A2.catalog.current_worlds.find(function (entry) { return entry.old === data.world; });
    if (decision) card.appendChild(A2.el("p", { class: "a2-worlds-declare-decision",
      text: "In the catalogue: " + decision.decision.charAt(0).toLowerCase() + decision.decision.slice(1) + "." }));
    container.replaceChildren(card);
  }
  api.render = render;
  if (root.A2 && root.A2.register) root.A2.register("worlds-declare", function (container) { legend(container, root.A2); });
})(typeof window !== "undefined" ? window : globalThis);
