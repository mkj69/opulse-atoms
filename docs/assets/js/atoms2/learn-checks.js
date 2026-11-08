(function (root) {
  "use strict";

  // Learn pages show hand-authored design records: a string with no notation v3 entry in any
  // registered world is design text, never machine notation posing as a formula.
  function designOpts(text, opts) {
    var options = Object.assign({}, opts);
    if (options.design === undefined && root.N3 && /[\s(<{\[]/.test(String(text)) &&
        !root.N3.lookup(String(text), options.world) && !root.N3.lookup(String(text))) options.design = true;
    return options;
  }


  function traceApply(staleGuard, budget) {
    if (!Number.isSafeInteger(budget) || budget < 0) throw new RangeError("fuel must be a nonnegative safe integer");
    var steps = 0;
    var calls = ["read(/a)", "eq(0,0)", "read(/l)", staleGuard ? "eq(0,1)" : "eq(0,0)"];
    if (!staleGuard) calls.push("write(/a,Q)", "write(/l,R)");
    var executed = [];
    for (var index = 0; index < calls.length; index++) {
      if (steps === budget) return { outcome: "Unknown(fuel)", steps: steps,
        trace: executed.join("; ") + ". Budget ran out before " + calls[index] + "." };
      executed.push(calls[index]);
      steps++;
    }
    return { outcome: staleGuard ? "Bottom(guard)" : "Ok(Doc<12:/a=Q,/l=R>)", steps: steps,
      trace: executed.join("; ") + (staleGuard ? ". The second old value did not match; no edits committed." : ". Both guards passed; two paths changed.") };
  }

  function certificateApplies(certificateHash, currentHash) {
    return certificateHash === currentHash;
  }

  function fixpointBreakdown(data) {
    var modes = data && data.modes;
    if (!modes || !modes.derivations || !modes.runs || !modes.derivations.fixpoint || !modes.runs.fixpoint) return null;
    var sample = modes.derivations.fixpoint.root;
    var total = A2.chargedLeaves(sample);
    if (total !== modes.runs.fixpoint.steps) throw new Error("Inconsistent fixpoint kernel trace");
    var children = sample.children.map(function (child) { return { name: child.def, steps: A2.chargedLeaves(child) }; });
    var expanded = sample.children.length === 1 && sample.children[0].children
      ? sample.children[0].children.map(function (child) { return { name: child.def, steps: A2.chargedLeaves(child) }; }) : [];
    if (expanded.reduce(function (sum, child) { return sum + child.steps; }, 0) !== total) throw new Error("Inconsistent expanded fixpoint trace");
    return { expression: modes.runs.fixpoint.expression, outcome: modes.runs.fixpoint.outcome_text,
      total: total, children: children, expanded: expanded, core_digest: modes.runs.fixpoint.core_digest };
  }

  function hashDefinition(text) {
    if (!root.crypto || !root.crypto.subtle) return Promise.reject(new Error("SHA-256 unavailable"));
    return root.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(function (bytes) {
      return Array.from(new Uint8Array(bytes), function (byte) { return byte.toString(16).padStart(2, "0"); }).join("");
    });
  }

  function definitionHashState(originalText, onResult, onError) {
    var originalHash = hashDefinition(originalText);
    var latestRequest = 0;
    return function (text) {
      var request = ++latestRequest;
      return Promise.all([originalHash, hashDefinition(text)]).then(function (hashes) {
        if (request === latestRequest) onResult(hashes[0], hashes[1]);
      }).catch(function (error) {
        if (request === latestRequest) onError(error);
      });
    };
  }

  function walkBadge(stage) {
    if (!stage.evidence) return stage.station === "callable" ? "executable" : "design";
    return stage.evidence.method;
  }

  function exampleCost(example) {
    var calls = example.trace.filter(function (step) {
      return step.layer === 0 && step.leaf && step.call !== "root";
    });
    var total = calls.reduce(function (sum, step) { return sum + step.steps; }, 0);
    if (total !== example.layer0_steps) throw new Error("Inconsistent kernel example cost");
    return { total: total, calls: calls };
  }

  function walkPanel(walk, href) {
    if (root.N3 && walk.notation3) root.N3.register(walk.notation3);
    var A2 = Object.create(root.A2);
    A2.expr = function (text, opts) {
      var worlds = walk.notation3 && walk.notation3.worlds || {};
      var world = Object.keys(worlds).find(function (id) {
        return worlds[id].formulas && Object.prototype.hasOwnProperty.call(worlds[id].formulas, text);
      }) || walk.world;
      return root.A2.expr(text, designOpts(text, Object.assign({ world: world }, opts)));
    };
    function attempt(text) {
      var world = Object.keys(walk.notation3 && walk.notation3.worlds || {})[0];
      if (root.N3 && root.N3.lookup(text, world)) return A2.expr(text);
      var segments = root.N3 && root.N3.prose(text, world);
      return segments ? segments.map(function (segment) {
        return segment[0] === "f" ? root.N3.render(segment[1], segment[2]) : document.createTextNode(segment[1]);
      }) : text;
    }
    var el = A2.el;
    var shortDigest = walk.core_digest.slice(0, 12);
    var grid = el("div", { class: "a2-walk-grid" });
    var panels = [];
    var buttons = [];
    var switcher = el("div", { class: "a2-walk-switcher", role: "group", "aria-label": "Select a kind's lifecycle" });
    walk.definitions.forEach(function (item, index) {
      var example = exampleCost(item.example);
      var stages = item.stages.map(function (stage) {
        var status = walkBadge(stage);
        var scope = stage.evidence && stage.evidence.scope;
        var evidence = stage.evidence && Object.assign({}, stage.evidence, { artifact: {
          file: walk.artifact, href: href, core_digest: walk.core_digest,
          content_hash: stage.content_hash, world_hash: walk.world_hash
        } });
        var badge = stage.evidence ? A2.scopedBadge(stage.evidence, scope && scope.domain,
          evidence && evidence.artifact) : status === "executable" ? A2.el("span", {}, "scope not recorded") : A2.badge("design");
        return el("li", {}, [el("strong", {}, stage.station[0].toUpperCase() + stage.station.slice(1)),
          badge, scope && stage.station === "verified" && A2.hasRecordedScope(stage.evidence) ? el("small", {},
            "Method: " + stage.evidence.method + ". " + scope.size + " cases.") : "",
          stage.cost && stage.station === "verified" ? el("small", {},
            "Accounted body: " + stage.cost.length + " nodes. Recorded body cost on " +
            stage.cost.steps.over.domain + ": " + stage.cost.steps.min + ".." +
            stage.cost.steps.max + " layer-0 calls; reuse " + stage.cost.reuse +
            ". Example trace: " + example.total + " layer-0 calls (" +
            example.calls.map(function (call) { return call.call + " " + call.steps; }).join(" + ") + ").") : "",
          stage.contract ? el("small", {}, "Contract: " + stage.contract.guarantees) : ""]);
      });
      var panel = el("article", { class: "a2-learn-card", id: "a2-walk-" + item.kind, hidden: index !== 0 }, [
        el("h3", {}, A2.KIND6_META[item.kind].word), el("p", {}, A2.expr(item.declaration, { design: !(root.N3 && root.N3.lookup(item.declaration)) })),
        el("p", {}, item.kind === "observation"
          ? "In this pinned export, the prior combinator's result is passed to observe; ?number{Even.val<24>} reads it through the granted read_number probe. Spec 0.5 also permits pure combinators on observed values."
          : item.demonstrates),
        el("ol", { class: "a2-learn-stages" }, stages),
        el("p", {}, [A2.expr(item.example.input), " ", A2.runBadge(item.example, href),
          " = ", A2.expr(item.example.outcome),
          "; " + example.total + " layer-0 calls."]),
        el("details", {}, [el("summary", {}, "Content hash, given calls and rejected attempt"),
          el("small", {}, "Content hash: " + item.stages[0].content_hash),
          el("h4", {}, "Unfolded given calls"),
          el("ol", {}, example.calls.map(function (step) {
            return el("li", {}, [A2.expr(step.call), " -> ", A2.expr(step.outcome),
              "; " + step.steps + " step(s)"]);
          })),
          el("p", {}, [A2.el("span", {}, "scope not recorded"),
            "Rejected: ", attempt(item.failure.attempt), ". Kernel: " + item.failure.error + "."])]),
      ]);
      panels.push(panel);
      grid.appendChild(panel);
      var button = el("button", { type: "button", "aria-pressed": String(index === 0),
        "aria-controls": panel.id, onclick: function () {
          panels.forEach(function (candidate, position) {
            candidate.hidden = position !== index;
            buttons[position].setAttribute("aria-pressed", String(position === index));
          });
        } }, A2.KIND6_META[item.kind].word);
      buttons.push(button);
      switcher.appendChild(button);
    });
    return el("section", { class: "a2-learn-pathway" }, [
      el("h2", {}, "Four independent lifecycles"),
        el("p", {}, ["Four separate integer-world examples at core SHA-256 ", shortDigest,
        ". Choose one kind to see its write, check, run, verify and promote stations. Focus on the three values in this run: Even.val<18> is constructed, bump_even returns Even.val<20>, and @twice[bump_even] returns Even.val<24>. The separate finite check covers 13 truth states (0..24); those are the scope, not 13 steps in this run. Open details for its content hash, exact trace and rejected attempt. ",
        el("a", { href: href }, "Inspect the versioned export"), "."]), switcher, grid,
      el("p", {}, [A2.el("span", {}, "scope not recorded"),
        "These definitions do not form a connected dependency tower in this pinned export. The observation receives the combinator's result as input. Core SHA-256 ", shortDigest,
        " recorded a rejection for ", attempt(walk.link_limit.attempt), ": ", walk.link_limit.error,
        ". Spec 0.5 still rejects this call: bump_even and advance take the truth sort Even. A different example may use pure combinators on already observed or explicitly public values, without passing the truth sort to them. The exported observation probe trace records only its granted given call."])
    ]);
  }

  function mount(host, data, walk) {
    if (root.N3) [data, walk, root.A2.kernelData].forEach(function (item) { if (item && item.notation3) root.N3.register(item.notation3); });
    var A2 = Object.create(root.A2);
    A2.expr = function (text, opts) {
      var sources = [data, walk, root.A2.kernelData];
      var world = data.world || Object.keys(data.notation3 && data.notation3.worlds || {})[0];
      sources.forEach(function (source) { Object.entries(source && source.notation3 && source.notation3.worlds || {}).forEach(function (entry) {
        if (entry[1].formulas && Object.prototype.hasOwnProperty.call(entry[1].formulas, text)) world = entry[0];
      }); });
      return root.A2.expr(text, designOpts(text, Object.assign({ world: world }, opts)));
    };
    var el = A2.el;
    function prose(text) {
      for (var source of [data, walk]) for (var world of Object.keys(source.notation3 && source.notation3.worlds || {})) {
        var segments = root.N3 && root.N3.prose(text, world);
        if (segments) return segments.map(function (segment) {
          return segment[0] === "f" ? root.N3.render(segment[1], segment[2]) : document.createTextNode(segment[1]);
        });
      }
      return text;
    }
    var agents = data.agents;
    var selected = el("p", { class: "a2-learn-result", role: "status" });
    var agentButtons = agents.map(function (agent, index) {
      return el("button", { type: "button", "aria-pressed": String(index === 0),
        onclick: function () {
          agentButtons.forEach(function (button, buttonIndex) {
            button.setAttribute("aria-pressed", String(buttonIndex === index));
            button.textContent = (buttonIndex === index ? "Selected: " : "Switch to: ") + agents[buttonIndex].name + " probe";
          });
          selected.replaceChildren("Selected: " + agent.name + ". Permitted probe ", A2.expr(agent.probe),
            ". Reading: ", A2.expr(agent.reading), ". ", prose(agent.permission));
        } }, agent.name + " probe");
    });
    agentButtons[0].click();
    var judge = el("div", { class: "a2-learn-result", hidden: true }, [
      el("strong", {}, "Judge view: full state"),
      el("p", {}, [A2.expr("Truth<card=R>", { design: true }), "; ", prose(data.truth.history)]),
      el("p", {}, "Only the judge can use this view. Changing which probe an agent reads cannot change the card or the judged answer.")
    ]);
    var judgeButton = el("button", { type: "button", "aria-expanded": "false", onclick: function () {
      judge.hidden = !judge.hidden;
      judgeButton.setAttribute("aria-expanded", String(!judge.hidden));
      judgeButton.textContent = judge.hidden ? "Show judge-only full state" : "Hide judge-only full state";
    } }, "Show judge-only full state");
    var definition = el("p", {}, A2.expr(data.definition));
    var hashLine = el("p", { class: "a2-learn-result", role: "status" }, "Calculating the definition hash...");
    var evidence = el("p");
    var compareHash = definitionHashState(data.definition, function (originalHash, currentHash) {
      hashLine.replaceChildren("SHA-256 of this definition: ", el("code", {}, currentHash));
      evidence.textContent = certificateApplies(originalHash, currentHash)
        ? "Illustrative certificate is attached to the original hash only. It is not a verified artifact and cannot promote this definition."
        : "Old illustrative certificate detached: the changed definition has a different hash. No inherited verification or promotion.";
    }, function () {
      hashLine.textContent = "SHA-256 unavailable in this browser. No certificate may attach.";
      evidence.textContent = "Hash comparison unavailable; do not infer verification.";
    });
    function showDefinition(text) {
      hashLine.textContent = "Calculating SHA-256...";
      definition.replaceChildren(A2.expr(text));
      return compareHash(text);
    }
    var editButton = el("button", { type: "button", onclick: function () {
      var edited = editButton.getAttribute("aria-pressed") !== "true";
      editButton.setAttribute("aria-pressed", String(edited));
      editButton.textContent = edited ? "Restore original definition" : "Edit definition";
      showDefinition(edited ? data.edited : data.definition);
    } }, "Edit definition");
    showDefinition(data.definition);
    var evidenceGrid = el("div", { class: "a2-learn-grid" });
    data.evidence.forEach(function (item) {
      evidenceGrid.appendChild(el("article", { class: "a2-learn-card" }, [A2.badge("design", { record: {
        method: item.method, scope: { description: item.scope },
        artifact: { file: "docs/assets/data/atoms2/checks.json", href: "../../assets/data/atoms2/checks.json" }
      } }), el("h3", {}, item.method), el("p", {}, item.scope)]));
    });
    var pathway = walkPanel(walk, host.dataset.walk);
    var guard = el("select", { "aria-label": "Second patch old-value guard" }, [
      el("option", { value: "stale" }, "stale guard at /l"), el("option", { value: "fresh" }, "matching guard at /l")]);
    var budget = el("select", { "aria-label": "Layer-0 fuel" }, [
      el("option", { value: "6" }, "fuel 6"), el("option", { value: "3" }, "fuel 3")]);
    var patchCall = el("p");
    var trace = el("div", { class: "a2-learn-result", role: "status" });
    function updateTrace() {
      var stale = guard.value === "stale";
      var patchText = data.patch_calls && data.patch_calls[stale ? "stale" : "fresh"];
      patchCall.replaceChildren(patchText ? A2.expr(patchText) : "No source published for this patch call.");
      var result = traceApply(stale, Number(budget.value));
      trace.replaceChildren(root.N3 && root.N3.lookup(result.outcome) ? A2.expr(result.outcome) : result.outcome,
        "; exact layer-0 cost: " + result.steps +
        " given calls. " + (root.N3 ? "Inspect the linked artifact for the full call trace." : result.trace));
    }
    guard.addEventListener("change", updateTrace);
    budget.addEventListener("change", updateTrace);
    updateTrace();
    var kernel = fixpointBreakdown(A2.kernelData);
    var boundaryPanel = kernel ? el("section", {}, [
      el("h2", {}, "One 12-junction reachability, two boundaries"),
      el("p", {}, ["Generated roads kernel trace: ", A2.expr(kernel.expression), " ",
        A2.runBadge({ input: kernel.expression, outcome: kernel.outcome, steps: kernel.total },
          "../../assets/js/atoms2/data.js"), " gives ",
        A2.expr(kernel.outcome), ". The root is one visible fixpoint step charging " + kernel.total + " layer-0 calls."]),
      el("p", { class: "a2-learn-result" }, "Folded: fix (" + kernel.total + ") -> " +
        kernel.children.map(function (child) { return child.name + " (" + child.steps + ")"; }).join(" + ") +
        ". Expand its first recursive call: " + kernel.expanded.map(function (child) {
          return child.name + " (" + child.steps + ")";
        }).join(" + ") + " = " + kernel.total + " layer-0 calls. Later junctions remain inside the recursive child; neither view discards their cost."),
      el("p", {}, ["Trace: generated data.js at core SHA-256 " + kernel.core_digest.slice(0, 12) + ". Graph: ",
        el("a", { href: "../../assets/data/atoms2/roads.json" }, "roads fixture"), ". A boundary only groups the same computation; it cannot change a result or failure."])
    ]) : el("p", { role: "status" }, "Kernel trace unavailable; no checked cost is claimed.");
    host.replaceChildren(
      el("section", { class: "a2-learn-hero" }, [A2.badge("design"),
        el("strong", {}, "A card stays hidden when the probe changes."),
        el("p", {}, prose(data.scenario)), el("p", { class: "a2-learn-subtle" }, data.source)]),
      el("section", {}, [el("h2", {}, "Evidence rules before the walkthrough"), evidenceGrid,
        el("p", {}, "These cards describe methods, not completed checks. A stored exhaustive or bounded check can support promotion only within its recorded scope and contract. A seeded sample cannot promote. Unknown(resource) is never a correct answer.")]),
      pathway,
      A2.learnEvidence.render(walk, host.dataset.walk),
      el("section", {}, [el("h2", {}, "Agent view versus judge view"),
        el("div", { class: "a2-learn-actions" }, agentButtons), selected, judgeButton, judge,
        el("p", {}, "Derived observations read granted probes and earlier observations. They never change the world. Here the judge uses the full state, the default judge view.")]),
      el("section", {}, [A2.badge("design"), el("h2", {}, "Edit a definition, lose its certificate"),
        definition, el("div", { class: "a2-learn-actions" }, editButton), hashLine, evidence,
        el("p", { class: "a2-learn-subtle" }, data.scope)]),
      el("section", {}, [A2.badge("design"), el("h2", {}, "Bottom is not Unknown"),
        el("p", {}, "Illustrative versions-style model: apply checks both old values before either edit. For this local model, read, eq and write are declared as given operations costing one layer-0 step each. The twelve-path base has 0 in every field. Switch the old value required at /l or limit fuel. This is computed in your browser, not a versions-world kernel certificate."),
        patchCall,
        el("div", { class: "a2-learn-actions" }, [guard, budget]), trace,
        el("p", {}, "Bottom(guard) is a completed stale-patch failure with no edits. Unknown(fuel) is a stopped calculation, never a correct answer. A boundary still charges the same layer-0 work.")]),
      boundaryPanel
    );
  }

  function init() {
    var host = document.querySelector('[data-a2-learn="checks"]');
    if (!host) return;
    Promise.all([host.dataset.source, host.dataset.walk].map(function (source) {
      return fetch(source).then(function (response) {
        if (!response.ok) throw new Error("Check data unavailable");
        return response.json();
      });
    })).then(function (results) { mount(host, results[0], results[1]); }).catch(function () {
      host.textContent = "Checks records could not load. Reload the page to retry.";
    });
  }

  root.A2 = root.A2 || {};
  root.A2.learnChecks = { traceApply: traceApply, certificateApplies: certificateApplies,
    fixpointBreakdown: fixpointBreakdown,
    hashDefinition: hashDefinition, definitionHashState: definitionHashState,
    walkBadge: walkBadge, exampleCost: exampleCost, walkPanel: walkPanel, mount: mount };
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
  }
})(typeof window !== "undefined" ? window : globalThis);
