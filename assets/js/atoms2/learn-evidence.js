(function (root) {
  "use strict";

  function render(record, href) {
    if (root.N3 && record.notation3) root.N3.register(record.notation3);
    var A2 = Object.create(root.A2);
    A2.expr = function (text, opts) {
      var worlds = record.notation3 && record.notation3.worlds || {};
      var world = Object.keys(worlds).find(function (id) {
        return worlds[id].formulas && Object.prototype.hasOwnProperty.call(worlds[id].formulas, text);
      }) || record.world;
      return root.A2.expr(text, Object.assign({ world: world }, opts));
    };
    var el = A2.el;
    var law = record.law_and_bridge.law;
    var bridge = record.law_and_bridge.bridge;
    var artifact = { file: record.artifact, href: href, core_digest: record.core_digest };
    function scopedBadge(item) {
      return A2.scopedBadge(item.evidence, item.scope, Object.assign({}, artifact, {
        content_hash: item.evidence && item.evidence.content_hash
      }));
    }
    return el("section", { class: "a2-learn-evidence" }, [
      el("h2", {}, "A law and bridge in the core export"),
      el("p", {}, ["These are separate integer and pair examples, not executions of the grammar designs. ",
        el("a", { href: href }, "Inspect the versioned kernel export"), "."]),
      el("div", { class: "a2-learn-grid" }, [
        el("article", { class: "a2-learn-card", "data-kind": "law" }, [scopedBadge(law),
          el("h3", {}, "Law: one replayed rewrite"), el("p", {}, A2.expr(law.declaration)),
          el("p", {}, A2.hasRecordedScope(law.evidence) ? "Bounded check: " + law.scope + ". " +
            law.evidence.scope.size + " inputs; checker: " + law.evidence.checker +
            "; content hash: " + law.evidence.content_hash + ". This does not establish a universal identity outside that domain." : "scope not recorded"),
          el("p", {}, ["Before: ", A2.expr(law.before), " = ", A2.expr(law.before_outcome)]),
          el("p", {}, ["After one law rewrite: ", A2.expr(law.after), " = ", A2.expr(law.after_outcome)]),
          el("p", { class: "a2-learn-result" }, "This designed rewrite uses " + law.rewrite_steps +
            " step; layer-0 replay charges " + law.charged_steps + " given calls for the result. No promotion record is published here.")]),
        el("article", { class: "a2-learn-card", "data-kind": "bridge" }, [scopedBadge(bridge),
          el("h3", {}, "Bridge: one commuting diagram"), el("p", {}, A2.expr(bridge.declaration)),
          el("p", {}, A2.hasRecordedScope(bridge.evidence) ? "Bounded check: " + bridge.scope + ". " +
            bridge.evidence.scope.size + " inputs; checker: " + bridge.evidence.checker +
            "; content hash: " + bridge.evidence.content_hash + ". The core checked " + bridge.pairs_checked +
            " ordered interface cases from " + bridge.domain_size + " pair values. This is not a universal claim." : "scope not recorded"),
          el("p", {}, [A2.expr(bridge.input), " = ", A2.expr(bridge.outcome), "; " +
            bridge.layer0_steps + " given call."]),
          el("p", { class: "a2-learn-result" }, ["For a nontrivial addition, both routes agree: ",
            A2.expr(bridge.diagram), ". The interface checked is pair addition versus integer addition."])])
      ])
    ]);
  }

  root.A2 = root.A2 || {};
  root.A2.learnEvidence = { render: render };
})(typeof window !== "undefined" ? window : globalThis);
