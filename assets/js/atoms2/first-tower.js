(function (root) {
  "use strict";

  var A2 = root.A2;

  function readableValue(value) {
    if (value && value.t === "nat" && value.tag === "val" && value.f.length === 1) {
      return "Nat<" + A2.formatValue(value.f[0]) + ">";
    }
    if (value && value.t === "frac" && value.tag === "val" && value.f.length === 1 &&
        value.f[0].t === "pair" && value.f[0].f.length === 2) {
      return "Frac<" + value.f[0].f.map(A2.formatValue).join(", ") + ">";
    }
    return A2.formatValue(value);
  }

  function resultText(outcome) {
    return "ok" in outcome ? "Ok(" + readableValue(outcome.ok) + ")" : A2.formatValue(outcome);
  }

  function displayedOutcome(outcome) {
    if (root.N3 && typeof root.N3.value === "function" && root.N3.value(outcome, "integer"))
      return A2.value(outcome, { world: "integer" });
    var machine = resultText(outcome);
    return root.N3 && !root.N3.lookup(machine, "integer") ?
      A2.el("span", {}, "No source published for this outcome.") : A2.expr(machine, { world: "integer" });
  }

  function displayedToken(name, kind, layer) {
    return root.N3 && !(typeof root.N3.name === "function" ? root.N3.name(name, "integer", kind) :
      root.N3.lookup(name, "integer")) ?
      A2.el("span", {}, "No source published") : A2.token(name, { kind: kind, layer: layer, world: "integer" });
  }

  function traceLines(node, depth) {
    var name = (node.name || "call").replace(/^nat(?=\.|$)/, "Nat").replace(/^frac(?=\.|$)/, "Frac");
    var label = name + " -> " + resultText(node.outcome) + " (" + node.steps + " steps)";
    var lines = ["  ".repeat(depth) + label];
    (node.children || []).forEach(function (child) { lines.push.apply(lines, traceLines(child, depth + 1)); });
    if (node.elided) lines.push("  ".repeat(depth + 1) + node.elided + " child calls elided");
    return lines;
  }

  function traceView(trace) {
    if (!root.N3) return A2.el("pre", {}, traceLines(trace, 0).join("\n"));
    var view = A2.el("pre");
    function visit(node, depth) {
      var name = node.name || "call";
      view.appendChild(document.createTextNode("  ".repeat(depth)));
      view.appendChild(root.N3.lookup(name, "integer") ? A2.expr(name, { world: "integer" }) :
        document.createTextNode("Recorded call"));
      view.appendChild(document.createTextNode(" -> "));
      view.appendChild(displayedOutcome(node.outcome));
      view.appendChild(document.createTextNode(" (" + node.steps + " steps)\n"));
      (node.children || []).forEach(function (child) { visit(child, depth + 1); });
      if (node.elided) view.appendChild(document.createTextNode("  ".repeat(depth + 1) + node.elided + " child calls elided\n"));
    }
    visit(trace, 0);
    return view;
  }

  function evidenceDetails(card, url) {
    var details = A2.el("details", { class: "first-tower-evidence" });
    var summary = A2.el("summary", { "aria-label": "Evidence for " + card.name });
    var info = A2.evidenceRecord({ evidence: card.evidence });
    var hasScope = A2.hasRecordedScope(card.evidence);
    summary.appendChild(A2.scopedBadge(card.evidence, info.size + " cases", { file: url, href: url }));
    details.appendChild(summary);
    var fields = A2.el("dl", {});
    var records = hasScope ? [["Library name", card.name], ["Method", info.method], ["Domain", info.domain],
      ["Scope size", info.size], ["Checked inputs", info.checkedInputs], ["Checks", info.checks],
      ["Content hash", info.artifact.contentHash]] : [["Library name", card.name], ["Scope", "scope not recorded"]];
    records.forEach(function (field) {
      if (field[1] === null || field[1] === undefined) return;
      fields.appendChild(A2.el("dt", {}, field[0]));
      fields.appendChild(A2.el("dd", {}, Array.isArray(field[1]) ? field[1].join(", ") :
        typeof field[1] === "object" ? JSON.stringify(field[1]) : String(field[1])));
    });
    details.appendChild(fields);
    details.appendChild(A2.el("a", { href: url }, "Open the run artifact"));
    return details;
  }

  function exampleView(example, url) {
    var view = A2.el("div", { class: "first-tower-run", hidden: true });
    if (example.input_from) {
      var source = A2.el("div", { class: "first-tower-source" });
      source.appendChild(A2.el("span", {}, "Input from core runs: "));
      example.input_from.forEach(function (step) {
        source.appendChild(A2.expr(step.call));
        if (step.outside_checked_scope) source.appendChild(A2.el("span", { class: "first-tower-scope" }, "Core run outside the checked scope"));
        source.appendChild(document.createTextNode(" -> "));
        source.appendChild(displayedOutcome(step.outcome));
        source.appendChild(document.createTextNode("; "));
      });
      view.appendChild(source);
    }
    view.appendChild(A2.el("span", { class: "first-tower-call" }, A2.expr(example.call)));
    view.appendChild(A2.runBadge(example, url));
    if (example.outside_checked_scope) view.appendChild(A2.el("span", { class: "first-tower-scope" }, "Core run outside the checked scope"));
    view.appendChild(A2.el("span", { class: "first-tower-result" }, displayedOutcome(example.outcome)));
    view.appendChild(A2.el("span", { class: "first-tower-steps" }, example.steps + " layer-0 steps"));
    var details = A2.el("details", { class: "first-tower-trace" });
    details.appendChild(A2.el("summary", {}, "Core call trace"));
    details.appendChild(traceView(example.trace));
    view.appendChild(details);
    return view;
  }

  function mount(host) {
    var url = host.getAttribute("data-src");
    fetch(url).then(function (response) {
      if (!response.ok) throw new Error("Tower data unavailable");
      return response.json();
    }).then(function (data) {
      if (data.schema !== "opulse.first_tower/1") throw new Error("Unsupported tower data");
      if (root.N3 && data.notation3) root.N3.register(data.notation3);
      if (root.N3 && root.N3.legendPanel && data.notation3) host.appendChild(root.N3.legendPanel(data.world || "integer"));
      var original = root.A2;
      A2 = Object.create(original);
      A2.expr = function (text, opts) { return original.expr(text, Object.assign({ world: data.world || "integer" }, opts)); };
      var list = A2.el("ol", { class: "first-tower-list", "aria-label": "Core-run integer definitions" });
      var views = [];
      var layers = Object.fromEntries(data.cards.map(function (card) { return [card.name, card.layer]; }));
      data.cards.forEach(function (card) {
        var item = A2.el("li", { class: "first-tower-row" });
        item.appendChild(A2.el("span", { class: "first-tower-layer" }, "L" + card.layer));
        item.appendChild(displayedToken((({ combinator: "@", observation: "?" })[card.kind] || "") + card.display_name,
          card.kind, card.layer));
        var summary = A2.el("details", { class: "first-tower-declaration" });
        var summaryHeading = A2.el("summary", {});
        summaryHeading.appendChild(A2.el("span", { class: "first-tower-summary-label" }, card.summary_label));
        var printed = card.summary_label.startsWith("Printed from");
        summaryHeading.appendChild(printed ? A2.expr(card.record_summary) : document.createTextNode(card.record_summary));
        summary.appendChild(summaryHeading);
        summary.appendChild(A2.el("div", { class: "first-tower-declaration-full" }, printed ? A2.expr(card.record_summary) : card.record_summary));
        summary.appendChild(A2.el("a", { href: host.hasAttribute("data-learn") ? "../worlds/integer/" : "worlds/integer/", text: "story design text" }));
        item.appendChild(summary);
        var deps = A2.el("p", { class: "first-tower-deps" });
        if (card.invented_dependencies.length) {
          deps.appendChild(document.createTextNode("Uses "));
          card.invented_dependencies.forEach(function (name) {
            deps.appendChild(displayedToken(({ nat: "Nat", frac: "Frac" })[name] || name,
              ({ nat: "object", frac: "object", repeat: "combinator" })[name] || "operation", layers[name]));
          });
        }
        var given = card.dependencies.filter(function (name) {
          return !card.invented_dependencies.some(function (invented) { return name.split(".")[0] === invented; });
        });
        if (given.length) deps.appendChild(document.createTextNode(" uses given: " + given.join(", ")));
        item.appendChild(deps);
        item.appendChild(evidenceDetails(card, url));
        var view = exampleView(card.example, url);
        item.appendChild(view);
        views.push(view);
        list.appendChild(item);
      });
      var controls = A2.el("div", { class: "first-tower-controls" });
      var button = A2.el("button", { type: "button", class: "a2-btn" }, "Step through the recorded run");
      var progress = A2.el("span", { role: "status", "aria-live": "polite" }, "Use the step button to see each recorded core result");
      var position = 0;
      button.addEventListener("click", function () {
        views.forEach(function (view) { view.hidden = true; });
        if (position === views.length) position = 0;
        views[position].hidden = false;
        position += 1;
        progress.textContent = "Recorded row " + position + " of " + views.length + " selected";
        button.textContent = position === views.length ? "Replay tower rows" : "Next tower row";
      });
      controls.appendChild(button);
      controls.appendChild(progress);
      host.appendChild(list);
      host.appendChild(controls);
      if (host.hasAttribute("data-learn")) {
        var failing = A2.el("div", { class: "first-tower-failure" });
        failing.appendChild(A2.el("h3", {}, "A real failed construction"));
        failing.appendChild(A2.runBadge(data.failing, url));
        failing.appendChild(A2.el("p", {}, [A2.expr(data.failing.call), " returns ", displayedOutcome(data.failing.outcome),
          " after " + data.failing.steps + " layer-0 steps."]));
        var failureTrace = A2.el("details", {});
        failureTrace.appendChild(A2.el("summary", {}, "Failed call trace"));
        failureTrace.appendChild(traceView(data.failing.trace));
        failing.appendChild(failureTrace);
        host.appendChild(failing);
      }
      var fallback = host.parentElement.querySelector("[data-first-tower-fallback]");
      if (fallback) fallback.hidden = true;
    }).catch(function () { host.textContent = "Core run data unavailable. The summary below remains readable."; });
  }

  function register() {
    A2 = root.A2;
    if (A2) A2.register("first-tower", mount);
  }
  if (typeof document !== "undefined" && !A2 && document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", register, { once: true });
  } else register();
  if (typeof module !== "undefined" && module.exports) module.exports = { resultText: resultText, traceLines: traceLines };
})(typeof window !== "undefined" ? window : globalThis);
