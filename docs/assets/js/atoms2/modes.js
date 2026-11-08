(function (root) {
  "use strict";
  var A2 = root.A2;
  var host = root.document && root.document.getElementById("a2-reference-modes");
  if (!host) return;
  var data = A2 && A2.kernelData && A2.kernelData.modes;
  if (root.N3 && A2 && A2.kernelData && A2.kernelData.notation3) root.N3.register(A2.kernelData.notation3);
  if (!data || !data.runs || !data.derivations ||
      ["fixpoint", "memo", "turns", "fold"].some(function (key) { return !data.runs[key] || !data.derivations[key]; }) ||
      !A2.boundary || !A2.boundary.render) {
    host.textContent = "Kernel traces are unavailable. See the versioned core specification.";
    return;
  }
  var descriptions = {
    fixpoint: ["Fixpoint: roads reachability", "Start at A. Extend the reachable junctions until another step adds none."],
    memo: ["Memoized recursion: repeated subcalls", "The recurrence repeats inputs. A cache saves real work without changing the charged unfolding."],
    turns: ["Interleaving: private observations", "Two agents alternate on a shared state. Each chooses using only its own observation."],
    fold: ["Derived structural fold: weighted tree", "An invented Tree generates its fold. Each branch combines results from its children."]
  };
  Object.keys(descriptions).forEach(function (key) {
    var run = data.runs[key];
    var panel = document.createElement("section");
    panel.className = "a2-mode-panel";
    var heading = document.createElement("h3");
    heading.textContent = descriptions[key][0];
    panel.appendChild(heading);
    var badge = document.createElement("span");
    badge.className = "ar-badge ar-badge-executable";
    badge.textContent = "Executable (core SHA-256 " + run.core_digest.slice(0, 12) + ")";
    panel.appendChild(badge);
    var explanation = document.createElement("p");
    explanation.textContent = descriptions[key][1];
    panel.appendChild(explanation);
    function line(label, value) {
      var row = document.createElement("p");
      row.className = "a2-mode-fact";
      var title = document.createElement("strong");
      title.textContent = label + ": ";
      row.appendChild(title);
      var worlds = A2.kernelData && A2.kernelData.notation3 && A2.kernelData.notation3.worlds || {};
      var world = Object.keys(worlds).find(function (id) {
        return worlds[id].formulas && Object.prototype.hasOwnProperty.call(worlds[id].formulas, value);
      }) || run.world || "integer";
      row.appendChild(A2.expr(value, { world: world }));
      panel.appendChild(row);
    }
    if (run.declaration) line("Invented object", run.declaration);
    line("Input", run.expression);
    line("Outcome", run.outcome_text);
    var accounting = document.createElement("p");
    accounting.className = "a2-mode-accounting";
    accounting.textContent = key === "memo"
      ? "Exact layer-0 steps: " + run.steps + " plain, " + run.memo_steps + " memo. " +
        "Executed work: " + run.work + " plain, " + run.memo_work +
        " memo. " + run.cache_hits + " memo-hit nodes in the charged trace; " +
        run.executed_cache_hits + " were cache lookups during execution. The rest appear inside replayed unfoldings and did not run again."
      : "Exact layer-0 steps: " + run.steps + ".";
    panel.appendChild(accounting);
    if (run.fixture) {
      var source = document.createElement("p");
      source.textContent = "Graph input: ";
      var link = document.createElement("a");
      link.href = "../assets/data/atoms2/roads.json";
      link.textContent = "roads graph fixture";
      source.appendChild(link);
      panel.appendChild(source);
    }
    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "a2-mode-toggle";
    toggle.textContent = (key === "fixpoint" ? "Hide " : "Explore ") + key + " kernel trace";
    toggle.setAttribute("aria-controls", "a2-mode-trace-" + key);
    toggle.setAttribute("aria-expanded", String(key === "fixpoint"));
    panel.appendChild(toggle);
    var viewer = document.createElement("div");
    viewer.id = "a2-mode-trace-" + key;
    viewer.className = "a2-mode-viewer";
    viewer.hidden = key !== "fixpoint";
    viewer.setAttribute("aria-label", descriptions[key][0] + " boundary explorer");
    panel.appendChild(viewer);
    host.appendChild(panel);
    toggle.addEventListener("click", function () {
      viewer.hidden = !viewer.hidden;
      toggle.setAttribute("aria-expanded", String(!viewer.hidden));
      toggle.textContent = (viewer.hidden ? "Explore " : "Hide ") + key + " kernel trace";
    });
    A2.boundary.render(viewer, { derivation: data.derivations[key], compact: true });
  });
})(typeof window !== "undefined" ? window : globalThis);
