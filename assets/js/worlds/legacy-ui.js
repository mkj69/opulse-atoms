(function (root) {
  "use strict";
  var IDS = ["successor", "integer", "clock", "bits", "strings", "lists", "logic", "perm", "rel", "grid", "pitch", "action"];
  function rule(world, operator) {
    var description = operator.plain || "Rule not recorded.";
    world.operators.forEach(function (entry, index) {
      description = description.split(entry.name).join("f" + (index + 1));
    });
    world.atoms.forEach(function (atom) {
      description = description.split(atom.symbol).join(atom.name);
    });
    return root.A2.worlds.ascii(description);
  }
  function worked(world) {
    return world.curated.map(function (name) {
      return world.operators.find(function (entry) { return entry.name === name; });
    }).filter(function (operator) { return operator && operator.examples && operator.examples.length; }).slice(0, 4);
  }
  function legacyBadge(world, subject) {
    return root.A2.badge("legacy", { record: {
      scope: { domain: world.world, description: subject + ". Published operations-only dialect; not a v2 verification result." },
      artifact: { file: world.world + ".json", href: "../../assets/data/worlds/" + world.world + ".json" }
    } });
  }
  function prose(world, text) {
    var segments = root.N3 && root.N3.prose(text, world.world);
    if (!segments) return root.N3 && /[^\x00-\x7f]/.test(text) ? "No source published for this rule." : root.A2.worlds.ascii(text);
    var container = root.A2.el("span");
    segments.forEach(function (segment) {
      container.appendChild(segment[0] === "f" ? root.N3.render(segment[1], segment[2]) : root.document.createTextNode(segment[1]));
    });
    return container;
  }
  function view(mount, worlds) {
    if (root.N3) worlds.forEach(function (world) { if (world.notation3) root.N3.register(world.notation3); });
    var A2 = root.A2, current = new URLSearchParams(root.location.search).get("world");
    var select = A2.el("select", { "aria-label": "Choose a legacy-v1 world" });
    worlds.forEach(function (world) {
      select.appendChild(A2.el("option", { value: world.world, text: A2.worlds.ascii(world.title) }));
    });
    var panel = A2.el("section", { class: "w2-section", "aria-live": "polite" });
    function draw() {
      var world = worlds.find(function (item) { return item.world === select.value; });
      var params = new URLSearchParams(root.location.search);
      params.set("world", world.world);
      root.history.replaceState(null, "", root.location.pathname + "?" + params + root.location.hash);
      panel.replaceChildren(A2.el("h2", { text: A2.worlds.ascii(world.title) }), legacyBadge(world, "World"),
        A2.el("p", { text: world.atoms.length + " given operations. " + world.operators.length +
          " generated operators, " + world.curated.length + " curated in the published artifact." }));
      if (root.N3 && root.N3.legendPanel && world.notation3) panel.appendChild(root.N3.legendPanel(world.world));
      var list = A2.el("div", { class: "w2-contract-grid" });
      world.atoms.forEach(function (atom) {
        var card = A2.el("div", { class: "w2-contract-cell" });
        card.appendChild(root.N3 && !root.N3.lookup(atom.name, world.world) ?
          A2.el("span", { text: "No source published" }) : A2.token(atom.name, { kind: "operation", origin: "given", world: world.world }));
        card.appendChild(legacyBadge(world, "Given operation " + atom.name));
        card.appendChild(A2.el("p", { class: "w2-foot", text: "Inputs: " +
          atom.params.map(function (param) { return A2.worlds.ascii(param.type); }).join(", ") +
          ". Output: " + A2.worlds.ascii(atom.result_type) + "." }));
        card.appendChild(A2.el("p", { class: "w2-foot" }, ["Rule: ", prose(world, atom.rule || atom.plain || "Not recorded")]));
        list.appendChild(card);
      });
      var selected = worked(world);
      var curated = A2.el("details", { class: "w2-legacy-curated", open: "" });
      curated.appendChild(A2.el("summary", { text: "Four worked examples from the published legacy data" }));
      var examples = A2.el("ol");
      selected.forEach(function (operator) {
        var record = A2.el("li", { class: "w2-contract-entry" });
        var identifier = "f" + (world.operators.indexOf(operator) + 1);
        var sourceName = root.N3 && root.N3.lookup(operator.name, world.world) ? operator.name : identifier;
        record.appendChild(root.N3 && !root.N3.lookup(sourceName, world.world) ?
          A2.el("span", { text: "No source published" }) : A2.token(sourceName, { kind: "operation", origin: "invented", world: world.world }));
        record.appendChild(legacyBadge(world, "Generated operator " + identifier));
        record.appendChild(A2.el("small", { text: "Legacy layer " + operator.layer + ". " +
          A2.worlds.ascii(operator.kind) + ". " + operator.params.length + " inputs; output sort " +
          A2.worlds.ascii(operator.result_type) + "." }));
        record.appendChild(A2.el("p", {}, ["Rule: ", prose(world, operator.plain || rule(world, operator))]));
        var sample = operator.examples[0];
        var machine = sample.call || sample.text || sample.expression;
        if (machine && root.N3 && !root.N3.lookup(machine, world.world)) machine = null;
        if (machine) record.appendChild(A2.expr(machine, { world: world.world }));
        else record.appendChild(A2.el("p", { text: "No source published for this example." }));
        examples.appendChild(record);
      });
      curated.appendChild(examples);
      panel.appendChild(curated);
      var given = A2.el("details", { class: "w2-legacy-given" }, [
        A2.el("summary", { text: "Inspect " + world.atoms.length + " given operations and rules" }), list]);
      panel.appendChild(given);
      panel.appendChild(A2.el("p", { class: "w2-foot", text: "The original challenge rules remain in the versioned source data. The linked JSON is an ASCII mirror. fN is an alias for the Nth generated operator, not a runnable legacy identifier." }));
      panel.appendChild(A2.el("a", { href: new URL("../../assets/data/worlds/" + world.world + ".json", root.location.href).href,
        text: "Inspect the ASCII legacy-v1 mirror" }));
    }
    select.value = IDS.includes(current) ? current : IDS[0];
    select.addEventListener("change", draw);
    mount.replaceChildren(select, panel);
    draw();
  }
  function start() {
    if (!root.A2 || !root.A2.worlds) return;
    root.document.querySelectorAll("[data-worlds-legacy]:not([data-ready])").forEach(function (mount) {
      mount.dataset.ready = "1";
      Promise.all(IDS.map(function (id) {
        return fetch(new URL("../../assets/data/worlds/" + id + ".json", root.location.href))
          .then(function (response) { if (!response.ok) throw Error("Legacy artifact unavailable"); return response.json(); });
      })).then(function (worlds) { view(mount, worlds); }).catch(function () {
        mount.textContent = "Legacy data could not be loaded. Reload to try again.";
      });
    });
  }
  if (typeof root.document !== "undefined") {
    if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", start);
    else start();
    if (root.document$ && root.document$.subscribe) root.document$.subscribe(start);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { ids: IDS, worked: worked, rule: rule, legacyBadge: legacyBadge };
})(typeof window !== "undefined" ? window : globalThis);
