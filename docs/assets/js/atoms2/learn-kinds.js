(function (root) {
  "use strict";

  // Learn pages show hand-authored design records: a string with no notation v3 entry in any
  // registered world is design text, never machine notation posing as a formula.
  // Copy the v3-ASCII spelling of a mark, else the chip's own text without its layer badge.
  function copyText(node) {
    var formula = typeof node.querySelector === "function" && node.querySelector("[data-n3-ascii]");
    if (formula) return formula.getAttribute ? formula.getAttribute("data-n3-ascii") : formula.dataset.n3Ascii;
    var parts = Array.from(node.childNodes || node.children || []).filter(function (child) {
      return !String(child.className || "").split(" ").includes("a2-layer-badge");
    });
    return parts.map(function (child) { return child.textContent; }).join("") || node.textContent;
  }

  function designOpts(text, opts) {
    var options = Object.assign({}, opts);
    if (options.design === undefined && root.N3 && /[\s(<{\[]/.test(String(text)) &&
        !root.N3.lookup(String(text), options.world) && !root.N3.lookup(String(text))) options.design = true;
    return options;
  }


  function countTrees(digits) {
    if (!Number.isSafeInteger(digits) || digits < 1 || digits > 48) throw new RangeError("digits must be 1..48");
    var counts = [1n];
    for (var size = 1; size < digits; size++) {
      var count = 0n;
      for (var left = 0; left < size; left++) count += counts[left] * counts[size - 1 - left];
      counts.push(count);
    }
    return counts[digits - 1];
  }

  function countWordTrees(word) {
    if (typeof word !== "string" || !/^Word<2(?:,"[+*]",2)*>$/.test(word)) throw new TypeError("expected a binary Word of 2 operands with quoted operators");
    return countTrees((word.match(/(?:<|,)2(?=,|>)/g) || []).length);
  }

  function dependencyEdges(cards) {
    var names = new Map(cards.map(function (card) {
      return [card.definition.split(" ")[1].split(/[([{:\s]/)[0], card.kind];
    }));
    return cards.map(function (card) {
      return { kind: card.kind, edges: card.depends_on.map(function (name) {
        return { name: name, kind: names.get(name) || null };
      }) };
    });
  }

  function mount(host, data, walk, core) {
    var exports = [data, walk, core].filter(Boolean);
    if (root.N3) exports.forEach(function (item) { if (item.notation3) root.N3.register(item.notation3); });
    var A2 = Object.create(root.A2);
    function worldFor(text) {
      for (var item of exports) for (var entry of Object.entries(item.notation3 && item.notation3.worlds || {})) {
        if (entry[1].formulas && Object.prototype.hasOwnProperty.call(entry[1].formulas, text)) return entry[0];
      }
      return data.world || data.id;
    }
    A2.expr = function (text, opts) { return root.A2.expr(text, designOpts(text, Object.assign({ world: worldFor(text) }, opts))); };
    A2.token = function (text, opts) { return root.A2.token(text, Object.assign({ world: worldFor(text) }, opts)); };
    function prose(text) {
      for (var item of exports) for (var world of Object.keys(item.notation3 && item.notation3.worlds || {})) {
        var segments = root.N3 && root.N3.prose(text, world);
        if (segments) return segments.map(function (segment) {
          return segment[0] === "f" ? root.N3.render(segment[1], segment[2]) : document.createTextNode(segment[1]);
        });
      }
      return text;
    }
    var el = A2.el;
    var status = el("p", { role: "status", class: "a2-learn-subtle" });
    var observation = core && core.rows.observation.example;
    var scopedRows = core && Object.values(core.rows).filter(function (row) { return A2.hasRecordedScope(row.evidence); });
    var unscopedRows = core && Object.values(core.rows).filter(function (row) { return !A2.hasRecordedScope(row.evidence); });
    var count = observation ? observation.outcome.match(/^Ok\(([0-9]+)\)$/)[1] : countWordTrees(data.input).toString();
    var artifact = host.dataset && host.dataset.core || "../../assets/data/atoms2/grammar_core.json";
    function kindExample(card) {
      if (!root.N3 || typeof root.N3.name !== "function") return "Example not yet available";
      var row = core && core.rows[card.kind];
      var recorded = row && row.example && root.N3 && root.N3.lookup(row.example.input, worldFor(row.example.input));
      if (recorded && !recorded.display.includes("::")) return root.N3.render(recorded.display, recorded.ascii);
      var examples = { object: "ExprTree", operation: "split", combinator: "@chart",
        observation: "?parse_count", law: "#assoc_count", bridge: "~to_rpn" };
      var exampleText = card.kind === "bridge" ? card.name : card.kind === "law" ? card.definition : card.form;
      var example = root.N3 && root.N3.lookup(exampleText, worldFor(exampleText));
      if (example && !example.display.includes("::")) return root.N3.render(example.display, example.ascii);
      var named = root.N3 && root.N3.name(examples[card.kind], worldFor(card.form), card.kind);
      if (named) return root.N3.render(named.display, named.ascii);
      return "Example not yet available";
    }
    var overview = el("section", { class: "a2-learn-overview" }, [A2.badge("design"),
      el("h2", {}, "Six kinds at a glance"),
      el("p", {}, "The prefix and shape identify each kind, not its color. These are roles, not consecutive layers. Select a kind to read its full definition later in the lesson."),
      el("table", {}, [
        el("thead", {}, el("tr", {}, [el("th", { scope: "col" }, "Kind"), el("th", { scope: "col" }, "Job"), el("th", { scope: "col" }, "Form")])),
        el("tbody", {}, data.cards.map(function (card) {
          return el("tr", {}, [
            el("th", { scope: "row" }, el("a", { href: "#kind-" + card.kind }, A2.KIND6_META[card.kind].word)),
            el("td", { class: "a2-learn-job" }, prose(card.job)),
            el("td", { class: "a2-learn-form" }, [el("span", { class: "a2-learn-form-label" }, "Example: "), kindExample(card)])
          ]);
        }))
      ])
    ]);
    var hero = el("section", { class: "a2-learn-hero" }, [
      A2.badge("design"),
      el("p", {}, A2.expr(data.expression)),
      el("strong", {}, count + " possible parse trees"),
      el("p", {}, core ? ["The grammar core runs ", A2.expr(observation.input), " ", A2.runBadge(observation, artifact),
        " and returns ", A2.expr(observation.outcome), " in " + observation.layer0_steps + " layer-0 steps. The world uses ",
        A2.expr(core.input), " for the same tokens as the schematic Word shown here. " +
        (A2.hasRecordedScope(core.rows.observation.evidence) ? "The bounded certificate covers " +
          core.rows.observation.scope + ". This eight-operand run is outside that checked domain." : "scope not recorded") ] :
        "The independent BigInt counter counts binary groupings of eight operands in your browser; no grammar-world run is loaded."),
      el("p", { class: "a2-learn-subtle" }, [core ? "Kernel artifact: " : "Design record: ",
        core ? el("a", { href: artifact }, core.digest.slice(0, 16)) : data.source])
    ]);
    var grid = el("div", { class: "a2-learn-grid" });
    var edges = dependencyEdges(data.cards);
    data.cards.forEach(function (card, index) {
      var row = core && core.rows[card.kind];
      var copy = A2.token(card.name, { kind: card.kind, layer: row ? row.layer : card.layer, button: true,
        class: card.kind === "observation" ? "a2-learn-observation" : "",
        title: card.kind === "law" ? "Copy scoped proposed law " + card.name : "Copy " + card.name });
      copy.setAttribute("aria-label", "Copy " + card.name);
      copy.addEventListener("click", function () {
        if (!root.navigator.clipboard || !root.navigator.clipboard.writeText) {
          status.textContent = "Clipboard unavailable. Select the token text to copy it.";
          return;
        }
        root.navigator.clipboard.writeText(copyText(copy)).then(function () {
          status.textContent = "Copied " + card.name;
        }, function () { status.textContent = "Clipboard blocked. Select the token text to copy it."; });
      });
      var dependencies = row ? row.depends_on : card.depends_on;
      var details = el("details", { class: "a2-learn-detail" }, [
        el("summary", {}, "Definition and direct prerequisites"),
        el("p", {}, row ? (A2.hasRecordedScope(row.evidence) ? "Core status: " + row.status + "; evidence method: " + row.evidence.method + " on its stated domain. " : "scope not recorded. ") + "The example is a recorded core run; its outcome alone does not extend that domain. The card token above is a design spelling." : prose(card.effect)),
        el("small", {}, [row ? "Core direct dependencies: " : "Selected direct dependencies: ", dependencies.map(function (name, position) {
          var edge = edges[index].edges.find(function (item) { return item.name === name; }) || { name: name, kind: null };
          return [position ? ", " : "", edge.kind
            ? el("a", { href: "#kind-" + edge.kind }, [A2.token(edge.name, { kind: edge.kind }), " (invented " + A2.KIND6_META[edge.kind].word + ")"])
            : edge.name + " (given or library)"];
        })]),
        el("small", {}, row ? row.declaration.label : "Design text (not parseable source)"),
        row && row.declaration.text ? el("p", {}, A2.expr(row.declaration.text)) :
          el("p", {}, A2.expr(row && row.declaration.display ? row.declaration.display : card.definition)),
        row && !row.declaration.text ? el("p", {}, "Core implementation: " + row.name + " at L" + row.layer) : null
      ]);
      var example = row && el("div", { class: "a2-learn-result" }, [
        row.example.outside_checked_scope ? el("p", {}, A2.hasRecordedScope(row.evidence) ?
          "Core run outside the definition's checked scope." : "scope not recorded") : null,
        el("p", {}, ["Core call: ", A2.expr(row.example.input), " ", A2.runBadge(row.example, artifact)]),
        el("p", {}, ["Result: ", A2.expr(row.example.outcome), "; " + row.example.layer0_steps + " layer-0 steps."]),
        row.failure ? el("p", {}, ["Unfinished draft: ", A2.expr(row.failure.input), " returns ",
          A2.expr(row.failure.outcome), "; " + row.failure.layer0_steps + " layer-0 steps. ",
          !A2.hasRecordedScope(row.evidence) ? "scope not recorded" : row.failure.outside_checked_scope ?
            "Core run outside the definition's checked scope." : "Within the definition's checked scope."]) : null,
        el("details", {}, [el("summary", {}, "Compact kernel trace"),
          el("ol", {}, row.example.trace.map(function (step) {
            return el("li", {}, [A2.expr(step.call), " (L" + step.layer + ", " + step.steps + " steps): ",
              A2.expr(step.outcome)]);
          }))])
      ]);
      grid.appendChild(el("article", { class: "a2-learn-card", id: "kind-" + card.kind,
        "data-kind": card.kind }, [row ? A2.scopedBadge(row.evidence, row.scope,
          { file: artifact, href: artifact }) : A2.badge("design"),
        el("h3", {}, A2.KIND6_META[card.kind].word),
        row ? el("small", {}, "Design spelling; the core call is below.") : null,
        copy,
        row ? example : null,
        details]));
    });
    var chain = el("div", { class: "a2-learn-result" }, [
      el("strong", {}, core ? "What the core counted" : "What the independent count computes"),
      el("p", {}, ["For ", A2.expr(core ? core.input : data.input), ", the result is " + count + " trees. A tree stores one grouping; the count includes all groupings. The postfix bridge below remains a design."]),
      el("p", {}, core ? "The independent BigInt counter counts binary groupings of the eight operands and also returns " + countWordTrees(data.input) + ". This is a separate calculation, not a second core certificate." : "The grammar world is not loaded here.")
    ]);
    var detailed = el("section", { class: "a2-learn-detail-tree" }, [A2.badge("design"),
      el("h2", {}, "One detailed tree, not 429 identical values"),
      el("p", {}, "The infix grouping illustrates precedence; it is schematic, not source."),
      el("p", {}, ["Fully grouped expression: ", A2.expr(data.detailed_tree.grouping)]),
      el("p", {}, ["Tree: ", A2.expr(data.detailed_tree.tree)]),
      el("p", {}, ["Postfix translation of this one tree: ", A2.expr(data.detailed_tree.postfix)]),
      el("p", {}, ["This grouping evaluates to ", A2.expr(data.detailed_tree.value), ". ", prose(data.detailed_tree.explanation)])
    ]);
    var template = el("section", {}, [A2.badge("design"),
      el("h2", {}, "One template, two separate checks"), el("p", {}, A2.expr(data.template.definition)),
      el("p", {}, "Checking a template family does not certify each instantiation. Each one goes through type checking, unfolding, verification, cost accounting, storage and promotion on its own scope.")]);
    var instances = el("div", { class: "a2-learn-grid" });
    data.template.instances.forEach(function (item) {
      instances.appendChild(el("article", { class: "a2-learn-card" }, [A2.badge("design"),
        el("h3", {}, item.name), el("p", {}, A2.expr(item.definition)),
        el("p", {}, ["Designed normalization: ", A2.expr(item.example), " -> ", A2.expr(item.result)]),
        el("p", {}, item.evidence)]));
    });
    template.appendChild(instances);
    var modes = el("div", { class: "a2-learn-grid" });
    data.modes.forEach(function (mode) {
      modes.appendChild(el("article", { class: "a2-learn-card" }, [
        A2.badge("design"), el("h3", {}, mode.name), el("p", {}, prose(mode.description)),
        el("p", {}, A2.expr(mode.example)), el("p", { class: "a2-learn-result" }, prose(mode.result))]));
    });
    host.replaceChildren(overview, hero,
      el("h2", {}, "Six roles, direct dependencies"),
      el("p", {}, "The first four cards show core layers and direct dependencies. The law and bridge still show proposed layers, not grammar-world certificates."),
      grid, chain, detailed,
      el("section", { class: "a2-learn-result" }, [el("h2", {}, "Core runs and remaining designs"),
        el("p", {}, core ? "The grammar artifact records " + scopedRows.map(function (row) { return row.evidence.method + " checks for " + row.name; }).join(" and ") + ". Core runs for " + unscopedRows.map(function (row) { return row.name; }).join(" and ") + " have no recorded checked-input scopes. The tree drawing, postfix bridge, law and template shown here remain designs. Their schematic declarations are not callable core source." : "Grammar core runs are unavailable. The displayed definitions remain designs.")]),
      el("section", { class: "a2-learn-result" }, [el("h3", {}, "Open and closed kinds"),
        el("p", {}, "A world declares open_kinds. The core checks new members of all six kinds when the world opens them. A closed kind cannot be invented there; given primitives remain callable. A boundary can fold a verified definition into one visible step, but it still charges the same layer-0 work and cannot change a result or failure.")]),
      template,
      el("section", {}, [A2.badge("design"), el("h2", {}, "Four more ways to combine"), modes,
        el("p", {}, ["These mode examples are design sketches; the grammar chart run above uses memoized recursion. Compare unfolding rules in ",
          el("a", { href: "../../reference/" }, "Reference / Semantics"), "."])]),
      walk ? A2.learnEvidence.render(walk, host.dataset.walk) : null,
      root.N3 && root.N3.legendPanel && data.notation3 ? root.N3.legendPanel(Object.keys(data.notation3.worlds)[0]) : null, status);
  }

  function init() {
    var host = document.querySelector('[data-a2-learn="kinds"]');
    if (!host) return;
    Promise.all([host.dataset.source, host.dataset.walk, host.dataset.core].map(function (source) {
      return fetch(source).then(function (response) {
        if (!response.ok) throw new Error("Grammar or kernel data unavailable");
        return response.json();
      });
    })).then(function (results) { mount(host, results[0], results[1], results[2]); }).catch(function (error) {
      host.textContent = "Grammar core data could not load: " + error.message + ". Reload the page to retry.";
    });
  }

  root.A2 = root.A2 || {};
  root.A2.learnKinds = { countTrees: countTrees, countWordTrees: countWordTrees, dependencyEdges: dependencyEdges, mount: mount };
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
  }
})(typeof window !== "undefined" ? window : globalThis);
