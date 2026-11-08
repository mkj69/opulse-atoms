/* Atoms v2 shared kit: kinds, icons, DOM helper, motion and value rendering.
 * Exposes window.A2. Components register with A2.register(name, mountFn) and are
 * mounted on [data-a2="<name>"]. See docs/spec/ui-atoms-v2.md.
 * Use A2.badge("design", {record: sourceRecord}) for an inspectable claim. Pass
 * only recorded fields; A2.evidenceRecord accepts core Evidence, world story
 * records, and design fixtures. An artifact link must point to a repo file. */
(function (root) {
  "use strict";
  var A2 = root.A2 || {};

  var STATUSES = ["written", "checked", "callable", "verified", "promoted"];

  /* Six atom kinds, shared by machine text and notation v3. */
  var KINDS6 = ["object", "operation", "combinator", "observation", "law", "bridge"];
  var KIND6_META = {
    object: { word: "Object", sigil: "Name<...>", question: "What is there?" },
    operation: { word: "Operation", sigil: "name(...)", question: "What can be done in one step?" },
    combinator: { word: "Combinator", sigil: "@name[...]", question: "How are steps put together?" },
    observation: { word: "Observation", sigil: "?name{...}", question: "What can the learner see?" },
    law: { word: "Law", sigil: "#name", question: "What holds on its checked scope?" },
    bridge: { word: "Bridge", sigil: "~name", question: "How does one world translate into another?" },
  };
  var KINDS = KINDS6.slice(0, 4);
  var KIND_META = KIND6_META;
  /* Kind of an ASCII identifier by its sigil: @ combinator, ? observation, # law, ~ bridge,
   * Capitalised object, otherwise operation. */
  function kindOf(name) {
    var c = String(name || "").charAt(0);
    if (c === "@") return "combinator";
    if (c === "?") return "observation";
    if (c === "#") return "law";
    if (c === "~") return "bridge";
    if (c >= "A" && c <= "Z") return "object";
    return "operation";
  }
  /* token(text, {kind, origin: "given"|"invented", layer, title}): one copyable chip. */
  function token(text, opts) {
    opts = opts || {};
    var dotted = /^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$/.exec(String(text));
    var exact = dotted && root.N3 && root.N3.name(String(text), opts.world);
    var object = dotted && !exact && root.N3 && root.N3.name(dotted[1], opts.world, "object");
    if (dotted && root.N3 && !exact && !object) return A2.el("code", {
      class: "a2-design-text", text: String(text)
    });
    // A stored design text (not parseable source) is never an atom chip.
    if (!dotted && root.N3 && typeof root.N3.isDesign === "function" && /[(<{\[]/.test(String(text)) &&
        root.N3.isDesign(String(text), opts.world)) return A2.el("code", { class: "a2-design-text", text: String(text) });
    var lookupKind = opts.kind || kindOf(text);
    var template = root.N3 && lookupKind === "template" && root.N3.name(String(text), opts.world, "template");
    var kind = object ? "object" : exact ? root.N3.kindOfMark(exact.display) || lookupKind :
      template ? root.N3.kindOfMark(template.display) || "object" : lookupKind;
    var origin = opts.given || opts.layer === 0 ? "given" : opts.origin || "invented";
    var attrs = { class: "a2-tok a2-k-" + kind + " a2-tok-" + origin + (opts.class ? " " + opts.class : ""),
      "data-kind": kind, title: opts.title || (KIND6_META[kind] ? KIND6_META[kind].word : kind) + (origin === "given" ? ", given" : opts.layer !== undefined && opts.layer !== null ? ", layer " + opts.layer : "") };
    if (origin !== "given" && opts.layer !== undefined && opts.layer !== null) attrs["data-layer"] = String(opts.layer);
    if (typeof document === "undefined") return A2.el(opts.button ? "button" : "span", Object.assign(attrs, { text: String(text) }));
    var formula = object || exact || template || root.N3 && !/[()[\]{}<>]/.test(String(text)) &&
      (root.N3.name(String(text), opts.world, lookupKind) || root.N3.name(String(text), opts.world)) || n3Formula(String(text), opts);
    if (formula && !formula.tagName && formula.display) formula = root.N3.render(formula.display, formula.ascii);
    // A bare atom name with no mark in this world's legend (a designed atom, not in any export)
    // shows as a plain word; the chip's kind style still tells its kind.
    var bareName = !formula && root.N3 && /^[@?#~]?[A-Za-z_][A-Za-z0-9_]*$/.test(String(text));
    if (bareName) attrs.class += " a2-design-name";
    else if (!formula && root.N3 && machineNotation(String(text), opts.world) && /[(<{\[@?#~=]/.test(String(text))) attrs.class += " n3-missing";
    // The mark's glyph tells the kind, so the inline kind icon (::before) is dropped for marks;
    // the copy text never includes the layer badge.
    if (formula) attrs.class += " a2-tok-n3";
    attrs["data-copy"] = formula && formula.getAttribute ? formula.getAttribute("data-n3-ascii") :
      bareName ? String(text).replace(/^[@?#~]/, "") : String(text);
    var chip = A2.el(opts.button ? "button" : "span", Object.assign(attrs, opts.button ? { type: "button" } : {}));
    if (formula) chip.appendChild(formula);
    else chip.textContent = bareName ? String(text).replace(/^[@?#~]/, "") : String(text);
    if (object) chip.appendChild(A2.el("span", {
      class: "a2-layer-badge a2-part-badge", text: ({ base: "canon", Stored: "store", Pack: "store", EdgeValid: "check" })[dotted[2]] ||
        dotted[2].replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ").toLowerCase()
    }));
    if (origin !== "given" && opts.layer != null) chip.appendChild(A2.el("span", {
      class: "a2-layer-badge", text: "L" + opts.layer, "aria-label": "Layer " + opts.layer
    }));
    return chip;
  }
  function n3Formula(text, opts) {
    if (!root.N3) return null;
    // A world-specific entry first; else an entry every registered world agrees on.
    var entry = root.N3.lookup(text, opts.world) || (opts.world !== undefined ? root.N3.lookup(text) : null);
    if (entry) return root.N3.render(entry.display, entry.ascii);
    if (Array.from(text).some(function (character) { return root.N3.ALLOWED.has(character); })) {
      try {
        if (root.N3.toDisplay(root.N3.toAscii(text)) === text)
          return root.N3.render(text, root.N3.toAscii(text));
      } catch (error) { return null; }
    }
    return null;
  }
  function machineNotation(text, world) {
    return /[()<>{}\[\]@?#~]/.test(text) || !!(root.N3 && root.N3.name(text, world));
  }
  function copyAscii(element) {
    var formula = element.matches && element.matches(".n3") ? element : element.querySelector(".n3");
    if (!formula || !root.navigator || !root.navigator.clipboard) return Promise.resolve(false);
    return root.navigator.clipboard.writeText(formula.getAttribute("data-n3-ascii")).then(function () { return true; });
  }
  /* badge(status, {scope, artifact, href, record}): the data-status badge required on every example.
   * status: design | executable | exhaustive | bounded | sampled | legacy. */
  var BADGE_TEXT = { design: "Designed example", executable: "Executable", exhaustive: "Exhaustively checked",
    bounded: "Bounded", sampled: "Seeded sample", legacy: "Legacy-v1" };
  function recorded(value) { return value === undefined || value === null || value === "" ? null : value; }
  function hasRecordedScope(evidence) {
    var scope = evidence && evidence.scope;
    var checked = scope && scope.checked;
    return !!(scope && typeof scope === "object" && Number.isSafeInteger(scope.size) && scope.size > 0 &&
      checked && checked !== "unrecorded" &&
      (Array.isArray(checked) ? checked.length > 0 :
        typeof checked === "object" ? typeof checked.sha256 === "string" &&
          /^[0-9a-f]{64}$/.test(checked.sha256) && checked.size > 0 : false));
  }
  function scopedBadge(evidence, label, artifact) {
    if (hasRecordedScope(evidence) && evidence.scope.partial) {
      var scope = evidence.scope;
      var text = "partial check: " + scope.size + " of " + scope.domain_total +
        " weightings of " + scope.topology;
      var button = A2.el("button", { class: "a2-scope-note", type: "button",
        "aria-label": text + ". View verification scope" }, text);
      button.addEventListener("click", function () {
        evidenceDrawer("partial check", { evidence: evidence, artifact: artifact }, button);
      });
      return button;
    }
    if (!hasRecordedScope(evidence) || !["bounded", "exhaustive", "sampled"].includes(evidence.method))
      return A2.el("span", { class: "a2-scope-note" }, "scope not recorded");
    if (evidence.method === "bounded" && evidence.scope.partial === false &&
        Number.isSafeInteger(evidence.scope.domain_total) &&
        evidence.scope.size === evidence.scope.domain_total && evidence.scope.topology)
      return A2.badge("bounded", { scope: "all " + evidence.scope.domain_total + " weightings of " +
        evidence.scope.topology, scopeStyle: "colon", record: { evidence: evidence, artifact: artifact } });
    return A2.badge(evidence.method, { scope: label, record: { evidence: evidence, artifact: artifact } });
  }
  function runBadge(run, href) {
    if (!run || !(run.call || run.input) || run.outcome === undefined ||
        !(Number.isSafeInteger(run.steps) || Number.isSafeInteger(run.layer0_steps)))
      return A2.el("span", { class: "a2-scope-note" }, "scope not recorded");
    return A2.badge("executable", { href: href });
  }
  function exactCost(value) {
    if (value && typeof value === "object") value = value.exact;
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }
  function chargedLeaves(node) {
    var children = node.children || [];
    return children.length ? children.reduce(function (total, child) {
      return total + chargedLeaves(child);
    }, 0) : node.emptyBody ? 0 : 1;
  }
  function evidenceRecord(raw) {
    raw = raw && typeof raw === "object" ? raw : {};
    var source = raw.evidence && typeof raw.evidence === "object" && !Array.isArray(raw.evidence) ? raw.evidence : raw;
    var scope = source.scope && typeof source.scope === "object" ? source.scope : {};
    var artifact = raw.artifact && typeof raw.artifact === "object" ? raw.artifact : {};
    var method = recorded(source.method);
    if (method) {
      method = String(method).toLowerCase();
      if (method === "seeded sample") method = "sampled";
    }
    return {
      method: scope.partial ? "partial check (recorded method: " + method + ")" : method,
      domain: recorded(scope.domain), size: recorded(scope.size), checkedInputs: recorded(scope.checked),
      domainTotal: recorded(scope.domain_total), topology: recorded(scope.topology),
      description: recorded(scope.description) || (typeof source.scope === "string" ? recorded(source.scope) : null),
      seed: recorded(source.seed), checks: recorded(source.checks),
      answerShape: recorded(raw.answer_shape), judgeView: recorded(raw.judge_view),
      visibleChannels: recorded(raw.learner_visible_channels), layer0Cost: exactCost(raw.layer0_cost),
      fullStateResult: recorded(raw.full_state_result), taskResult: recorded(raw.task_projected_result),
      bottom: recorded(raw.bottom), unknown: recorded(raw.unknown),
      artifact: {
        file: recorded(artifact.file), href: recorded(artifact.href), schema: recorded(artifact.schema) || recorded(raw.schema),
        version: recorded(artifact.version) || recorded(raw.version), coreDigest: recorded(artifact.core_digest) || recorded(raw.core_digest),
        contentHash: recorded(artifact.content_hash) || recorded(source.content_hash) || recorded(raw.content_hash),
        worldHash: recorded(source.world_hash), depsHash: recorded(source.deps_hash)
      }
    };
  }
  function evidenceValue(value) {
    if (value === null || value === undefined || value === "") return "not recorded";
    if (Array.isArray(value)) return value.length ? value.join(", ") : "not recorded";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }
  function evidenceDrawer(status, record, trigger) {
    var info = evidenceRecord(record);
    var dialog = el("dialog", { class: "a2-evidence-drawer", "aria-label": "Verification scope" });
    var closeButton = el("button", { type: "button", class: "a2-evidence-close" }, "Close evidence details");
    var fields = [
      ["Status", BADGE_TEXT[status] || status], ["Method", info.method], ["Domain", info.domain],
      ["Scope size", info.size], ["Checked-input record", info.checkedInputs],
      ["Total weightings", info.domainTotal], ["Topology", info.topology],
      ["Scope description", info.description], ["Seed", info.seed],
      ["Checks", info.checks], ["Answer shape", info.answerShape], ["Judge view", info.judgeView],
      ["Learner-visible channels", info.visibleChannels], ["Layer-0 cost", info.layer0Cost === null ? "not run" : info.layer0Cost],
      ["Full-state result", info.fullStateResult], ["Task-projected result", info.taskResult],
      ["Bottom in this run", info.bottom], ["Unknown in this run", info.unknown],
      ["Artifact file", info.artifact.file], ["Artifact schema", info.artifact.schema],
      ["Artifact version", info.artifact.version], ["Core SHA-256", info.artifact.coreDigest],
      ["Content hash", info.artifact.contentHash], ["World hash", info.artifact.worldHash],
      ["Dependency hash", info.artifact.depsHash]
    ];
    var list = el("dl", { class: "a2-evidence-fields" });
    fields.forEach(function (field) {
      list.appendChild(el("dt", {}, field[0]));
      list.appendChild(el("dd", {}, evidenceValue(field[1])));
    });
    dialog.appendChild(el("h2", {}, "Verification scope"));
    dialog.appendChild(el("p", {}, status === "design" ? "Design only. No verification run is claimed." :
      "Only the recorded scope supports this claim. Unknown is never a correct result."));
    dialog.appendChild(closeButton);
    dialog.appendChild(list);
    var artifactLink = null;
    if (info.artifact.file && info.artifact.href && /^(\.{1,2}\/|\/(?!\/))/.test(info.artifact.href)) {
      artifactLink = el("a", { href: info.artifact.href, class: "a2-evidence-artifact" }, "Open artifact: " + info.artifact.file);
      dialog.appendChild(artifactLink);
    }
    document.body.appendChild(dialog);
    function close() {
      if (dialog.close && dialog.open) dialog.close();
      dialog.remove();
      trigger.focus();
    }
    closeButton.addEventListener("click", close);
    dialog.addEventListener("cancel", function (event) { event.preventDefault(); close(); });
    dialog.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { event.preventDefault(); close(); }
      if (event.key === "Tab" && (
        (event.shiftKey && document.activeElement === closeButton) ||
        (!event.shiftKey && document.activeElement === (artifactLink || closeButton)))) {
        event.preventDefault();
        (artifactLink && event.shiftKey ? artifactLink : closeButton).focus();
      }
    });
    if (dialog.showModal) dialog.showModal();
    else { dialog.setAttribute("open", ""); dialog.setAttribute("role", "dialog"); dialog.setAttribute("aria-modal", "true"); }
    closeButton.focus();
    return dialog;
  }
  function badge(status, opts) {
    opts = opts || {};
    var text = BADGE_TEXT[status] || status;
    if (opts.scope && (status === "exhaustive" || status === "bounded" || status === "sampled"))
      text += opts.scopeStyle === "colon" ? ": " + opts.scope : " (" + opts.scope + ")";
    var attrs = { class: "a2-badge a2-badge-" + status, title: opts.artifact ? "Artifact: " + opts.artifact : text };
    if (opts.record || opts.evidence) {
      attrs.type = "button";
      attrs["aria-label"] = text + ". View verification scope";
      var button = el("button", attrs, text);
      button.addEventListener("click", function () { evidenceDrawer(status, opts.record || opts.evidence, button); });
      return button;
    }
    if (opts.href) { attrs.href = opts.href; return el("a", attrs, text); }
    return el("span", attrs, text);
  }
  /* expr(text, {given: [names], invented: [names]}): style only known provenance. */
  var IDENT = /([@?#~]?[A-Za-z_][A-Za-z0-9_]*)/g;
  var OUTCOME = /(^|[^A-Za-z0-9_])(Ok|Bottom|Unknown)\(/g;
  var KEYWORDS = { obj: true, op: true, comb: true, obs: true, law: true,
    bridge: true, where: true, for: true, and: true, canon: true, sealed: true, given: true };
  function expr(text, opts) {
    opts = opts || {};
    if (opts.design === true || root.N3 && typeof root.N3.isDesign === "function" && root.N3.isDesign(String(text), opts.world))
      return el("code", { class: "a2-design-text" }, String(text));
    var notation = n3Formula(String(text), opts);
    if (!notation && root.N3 && /^[@?#~]?[A-Za-z_][A-Za-z0-9_]*$/.test(String(text))) {
      var named = root.N3.name(String(text), opts.world, opts.kind);
      if (named) notation = root.N3.render(named.display, named.ascii);
      else return el("code", { class: "a2-expr a2-design-name" }, String(text).replace(/^[@?#~]/, ""));
    }
    if (notation) return el("code", { class: "a2-expr" }, notation);
    if (root.N3) return el("code", { class: "a2-expr" + (machineNotation(String(text), opts.world) && /[(<{\[@?#~=]/.test(String(text)) ? " n3-missing" : "") }, String(text));
    var given = Array.isArray(opts.given) ? opts.given : [];
    var invented = Array.isArray(opts.invented) ? opts.invented : [];
    var box = el("code", { class: "a2-expr" });
    text = String(text);
    function appendIdentifiers(start, end) {
      var last = start;
      var section = text.slice(start, end);
      section.replace(IDENT, function (match, name, offset) {
        var position = start + offset;
        if (position > last) box.appendChild(document.createTextNode(text.slice(last, position)));
        var next = text.charAt(position + match.length);
        var kind = "@?#~".indexOf(name.charAt(0)) >= 0 ? kindOf(name)
          : /^[A-Z]/.test(name) ? "object"
          : !KEYWORDS[name] && next === "(" ? "operation" : null;
        if (name === "Ok" || name === "Bottom" || name === "Unknown") {
          box.appendChild(el("span", { class: "a2-x-outcome" }, name));
        } else if (KEYWORDS[name]) box.appendChild(el("span", { class: "a2-x-keyword" }, name));
        else if (kind) {
          var origin = given.indexOf(name) >= 0 ? "given" : invented.indexOf(name) >= 0 ? "invented" : "neutral";
          box.appendChild(el("span", { class: "a2-x a2-k-" + kind + " a2-x-" + origin,
            "data-kind": kind, "data-origin": origin }, name));
        } else box.appendChild(document.createTextNode(name));
        last = position + match.length;
        return match;
      });
      if (last < end) box.appendChild(document.createTextNode(text.slice(last, end)));
    }
    var cursor = 0;
    OUTCOME.lastIndex = 0;
    var match;
    while ((match = OUTCOME.exec(text))) {
      var start = match.index + match[1].length;
      if (start < cursor) continue;
      var depth = 1;
      var end = OUTCOME.lastIndex;
      while (end < text.length && depth) {
        if (text.charAt(end) === "(") depth++;
        if (text.charAt(end) === ")") depth--;
        end++;
      }
      if (depth) continue;
      appendIdentifiers(cursor, start);
      box.appendChild(el("span", { class: "a2-x-outcome" }, text.slice(start, end)));
      cursor = end;
      OUTCOME.lastIndex = end;
    }
    appendIdentifiers(cursor, text.length);
    return box;
  }

  function legend() {
    return el("div", { class: "a2-legend", "aria-label": "Six atom kinds" }, [
      KINDS6.map(function (kind) { return kindBadge(kind); }),
      el("span", { class: "a2-legend-note" }, "Filled: given. Outlined: invented.")
    ]);
  }

  var SVGNS = "http://www.w3.org/2000/svg";
  var ICON_PATHS = {
    object: '<path d="M3 3h10l4 4v10H3zM13 3v4h4" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    operation: '<rect x="2" y="5" width="16" height="10" rx="5" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    combinator: '<path d="M5 3H2v14h3m10-14h3v14h-3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M7 6h6v8H7z" fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="2 2"/>',
    observation: '<path d="M2 10Q10 1 18 10Q10 19 2 10z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="10" cy="10" r="2.4" fill="currentColor"/>',
    law: '<rect x="2" y="3" width="16" height="14" rx="1" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M6 8h8M6 12h8" stroke="currentColor" stroke-width="1.8"/>',
    bridge: '<path d="M2 4h10l6 6-6 6H2zM6 10h8m-3-3 3 3-3 3" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  };

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
        else if (key.slice(0, 2) === "on" && typeof value === "function") node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : String(value));
      });
    }
    append(node, children);
    return node;
  }

  function append(node, children) {
    if (children === null || children === undefined || children === false) return node;
    if (!Array.isArray(children)) children = [children];
    children.forEach(function (child) {
      if (child === null || child === undefined || child === false) return;
      if (Array.isArray(child)) append(node, child);
      else node.appendChild(typeof child === "object" ? child : document.createTextNode(String(child)));
    });
    return node;
  }

  function icon(kind, label, origin) {
    var svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 20 20");
    svg.setAttribute("class", "a2-icon a2-k-" + kind);
    if (label) {
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", label);
    } else {
      svg.setAttribute("aria-hidden", "true");
    }
    svg.innerHTML = ICON_PATHS[kind] || "";
    return svg;
  }

  function kindBadge(kind) {
    return el("span", { class: "a2-kind a2-k-" + kind }, [icon(kind), KIND_META[kind] ? KIND_META[kind].word : kind]);
  }

  /* chip(def, opts): shape + name + layer. opts.button makes it a <button>. */
  function chip(def, opts) {
    opts = opts || {};
    var kind = def.kind || "operation";
    var origin = def.given || def.layer === 0 ? "given" : def.origin || "invented";
    var cls = "a2-chip a2-k-" + kind + (origin === "invented" ? " a2-invented" : "") + (opts.class ? " " + opts.class : "");
    var attrs = { class: cls, "data-def": def.name, "data-kind": kind, title: (KIND_META[kind] ? KIND_META[kind].word : kind) + " " + def.name + (origin === "given" ? "" : def.layer != null ? ", layer " + def.layer : "") + ", " + origin };
    if (origin !== "given" && def.layer != null) attrs["data-layer"] = String(def.layer);
    if (opts.button) { attrs.type = "button"; if (opts.onclick) attrs.onclick = opts.onclick; }
    var world = opts.world || def.world;
    var mark = root.N3 && root.N3.name(def.name, world, kind) || root.N3 && root.N3.name(def.name, world);
    var children = [icon(kind), mark ? root.N3.render(mark.display, mark.ascii) : el("span", { class: "a2-chip-name", text: def.name })];
    if (origin !== "given" && def.layer != null) children.push(el("span", {
      class: "a2-layer-badge", text: "L" + def.layer, "aria-label": "Layer " + def.layer
    }));
    return el(opts.button ? "button" : "span", attrs, children);
  }

  /* Values. Accepts plain JS values (number, string, boolean) and the core JSON encoding
   * (opulse.value/2): {t: "int", v} | {t: "str", v} | {t: sort, tag, f: [values]}. Field names
   * come from A2.sorts[sort][tag]; sorts listed in A2.sealedSorts show sealed unless
   * opts.open. Exports may substitute {repr: text} or {elided_value: summary, chars: count}.
   * Outcomes: {ok: value} | {bottom: reason} | {unknown: resource}. */
  function isCard(v) { return !!(v && typeof v === "object" && typeof v.t === "string" && "tag" in v); }
  function isAtomJson(v) { return !!(v && typeof v === "object" && (v.t === "int" || v.t === "str") && "v" in v && !("tag" in v)); }
  function isOutcome(v) { return !!(v && typeof v === "object" && !("t" in v) && ("ok" in v || "bottom" in v || "unknown" in v)); }
  function fieldNames(sort, tag) {
    var s = A2.sorts && A2.sorts[sort];
    return (s && s[tag]) || null;
  }
  /* A structural list (sort list[...], tags nil / cons) as an array of items, else null. */
  function listItems(v) {
    if (!isCard(v) || v.t.slice(0, 5) !== "list[") return null;
    var items = [];
    while (isCard(v) && v.tag === "cons" && v.f && v.f.length === 2) { items.push(v.f[0]); v = v.f[1]; }
    return isCard(v) && v.tag === "nil" ? items : null;
  }
  function isSealed(sort) { return !!(A2.sealedSorts && A2.sealedSorts[sort]); }
  function displaySort(sort) { return ({ fraction: "Frac", "list[int]": "List<Int>", robot_state: "RobotState",
    machine_state: "MachineState", byte: "Byte", reg: "Reg" })[sort] || sort; }

  function value(v, opts) {
    opts = opts || {};
    if (typeof document === "undefined") return A2.expr(formatValue(v, opts), opts);
    var extra = opts.role === "result" ? " a2-v-result" : opts.role === "focus" ? " a2-v-focus" : "";
    var notation = root.N3 && root.N3.value(v, opts.world);
    if (notation) return el("span", { class: "a2-v a2-v-atom" + extra }, root.N3.render(notation.display, notation.ascii));
    if (isOutcome(v)) return outcome(v, opts);
    if (isExportText(v)) return el("span", { class: "a2-v a2-v-atom" + extra, text: formatValue(v, opts) });
    if (isAtomJson(v)) v = v.v;
    var items = opts.open ? null : listItems(v);
    if (items) return el("span", { class: "a2-v a2-v-atom" + extra, title: displaySort(v.t) + ": " + formatValue(v, opts), text: formatValue(v, opts) });
    if (isCard(v)) {
      if (v.t === "bool" && (!v.f || !v.f.length)) return el("span", { class: "a2-v a2-v-atom" + extra, text: v.tag });
      var sealed = isSealed(v.t) && !opts.open;
      var box = el("span", { class: "a2-v a2-v-card" + (sealed ? " a2-v-sealed" : "") + extra, "data-sort": v.t, title: displaySort(v.t) });
      box.appendChild(el("span", { class: "a2-v-tag", text: sealed ? displaySort(v.t) : v.tag === "fraction" ? "Frac" : v.tag }));
      var fields = el("span", { class: "a2-v-fields" });
      if (sealed) {
        fields.appendChild(el("span", { class: "a2-v-fname", text: opts.sealedText || "sealed" }));
      } else {
        var names = fieldNames(v.t, v.tag) || [];
        (v.f || []).forEach(function (item, i) {
          fields.appendChild(el("span", { class: "a2-v-field" }, [
            names[i] ? el("span", { class: "a2-v-fname", text: names[i] }) : null, value(item, { open: opts.open, world: opts.world }),
          ]));
        });
      }
      box.appendChild(fields);
      return box;
    }
    if (typeof v === "boolean") return el("span", { class: "a2-v a2-v-atom" + extra, text: v ? "true" : "false" });
    if (typeof v === "string") return el("span", { class: "a2-v a2-v-atom" + extra, text: v });
    return el("span", { class: "a2-v a2-v-atom" + extra, text: formatValue(v, opts) });
  }

  function outcome(o, opts) {
    var notation = root.N3 && root.N3.value(o, opts && opts.world);
    if (notation) return el("span", { class: "a2-v a2-v-atom" }, root.N3.render(notation.display, notation.ascii));
    if ("bottom" in o) return el("span", { class: "a2-v a2-v-bottom", title: "Bottom: " + o.bottom, text: "Bottom(" + o.bottom + ")" });
    if ("unknown" in o) return el("span", { class: "a2-v a2-v-unknown", title: "Unknown: budget exhausted; never judged correct", text: "Unknown(" + o.unknown + ")" });
    return value(o.ok, opts);
  }

  function formatCard(v, opts) {
    var notation = root.N3 && root.N3.value(v, opts && opts.world);
    if (notation) return notation.display;
    if (v.t === "bool" && (!v.f || !v.f.length)) return v.tag;
    var sort = displaySort(v.t);
    var constructor = v.tag === v.t || v.t === "fraction" && v.tag === "fraction" ? sort : sort + "." + v.tag;
    var machine = constructor + "<" + (v.f || []).map(function (item) { return formatValue(item, opts); }).join(", ") + ">";
    var entry = root.N3 && root.N3.lookup(machine, opts && opts.world);
    return entry ? entry.display : machine;
  }

  function asciiText(text) {
    return text.replace(/[^\x20-\x7e]/g, function (character) {
      return "\\u" + character.charCodeAt(0).toString(16).padStart(4, "0");
    });
  }

  function isExportText(v) {
    return !!(v && typeof v === "object" && !Array.isArray(v) &&
      (typeof v.repr === "string" || "elided_value" in v));
  }

  function exportText(v) {
    if (typeof v.repr === "string") return asciiText(v.repr);
    var count = Number.isSafeInteger(v.chars) && v.chars >= 0 ? " (" + v.chars + " chars)" : "";
    var summary = typeof v.elided_value === "string" && v.elided_value ? ": " + asciiText(v.elided_value) : "";
    return "value elided" + count + summary;
  }

  /* Plain text form; cards use ASCII angle brackets. */
  function formatValue(v, opts) {
    var notation = root.N3 && root.N3.value(v, opts && opts.world);
    if (notation) return notation.display;
    var stored = typeof v === "string" ? v : isExportText(v) && v.repr || JSON.stringify(v);
    var entry = root.N3 && root.N3.lookup(stored, opts && opts.world);
    if (entry) return entry.display;
    if (isOutcome(v)) {
      if ("bottom" in v) return "Bottom(" + v.bottom + ")";
      if ("unknown" in v) return "Unknown(" + v.unknown + ")";
      return formatValue(v.ok);
    }
    if (isExportText(v)) return exportText(v);
    if (isAtomJson(v)) return v.t === "str" ? formatValue(v.v) : String(v.v);
    var items = listItems(v);
    if (items) return "List<" + items.map(function (item) { return formatValue(item, opts); }).join(", ") + ">";
    if (isCard(v)) return formatCard(v, opts);
    if (Array.isArray(v)) return "List<" + v.map(function (item) { return formatValue(item, opts); }).join(", ") + ">";
    if (typeof v === "string") return asciiText(JSON.stringify(v));
    if (typeof v === "boolean") return v ? "true" : "false";
    if (v && typeof v === "object") return root.N3 ? "value not available" : asciiText(JSON.stringify(v));
    return String(v);
  }

  /* Boundary (core spec section 10): a call of definition d at call path p is opened iff d is
   * not given, d.kind is in kinds, d.name is not in keep_names, and one of: d.layer >= depth,
   * d.name in open_names, p in open_paths. Arrays are accepted for the name and path sets. */
  var ALL_KINDS = KINDS6;
  function boundary(b) {
    b = b || {};
    return { depth: b.depth === undefined ? null : b.depth, open_names: (b.open_names || []).slice(),
      keep_names: (b.keep_names || []).slice(), open_paths: (b.open_paths || []).map(function (p) { return p.slice(); }),
      kinds: (b.kinds || ALL_KINDS).slice() };
  }
  function pathKey(p) { return (p || []).join("."); }
  function isOpened(call, b) {
    if (call.given) return false;
    if (b.kinds.indexOf(call.kind) < 0) return false;
    if (b.keep_names.indexOf(call.def) >= 0) return false;
    if (b.depth !== null && b.depth !== undefined && call.layer >= b.depth) return true;
    if (b.open_names.indexOf(call.def) >= 0) return true;
    var key = pathKey(call.path);
    return b.open_paths.some(function (p) { return pathKey(p) === key; });
  }

  /* Evidence badge: {method, scope, seed}. */
  function scopeText(scope) {
    if (!scope) return "";
    if (typeof scope === "string") return scope;
    return scope.domain + (scope.size ? " (" + scope.size.toLocaleString("en-US") + ")" : "");
  }
  function evidence(ev) {
    if (!ev) return el("span", { class: "a2-ev a2-ev-sampled", text: "not checked" });
    var parts = [el("span", { class: "a2-ev-method", text: ev.method })];
    if (ev.scope) parts.push(el("span", { text: scopeText(ev.scope) }));
    if (ev.seed !== undefined && ev.seed !== null) parts.push(el("span", { class: "a2-chip-layer", text: "seed " + ev.seed }));
    if (ev.method === "sampled") parts.push(el("span", { class: "a2-chip-layer", text: "not promotable" }));
    var title = "Checked: " + ev.method + (ev.scope && ev.scope.description ? ", " + ev.scope.description : "");
    return el("span", { class: "a2-ev a2-ev-" + ev.method, title: title }, parts);
  }

  /* Motion. */
  function reducedMotion() {
    return !!(root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function bezier(x1, y1, x2, y2) {
    function a(p1, p2) { return 1 - 3 * p2 + 3 * p1; }
    function b(p1, p2) { return 3 * p2 - 6 * p1; }
    function c(p1) { return 3 * p1; }
    function at(t, p1, p2) { return ((a(p1, p2) * t + b(p1, p2)) * t + c(p1)) * t; }
    function slope(t, p1, p2) { return 3 * a(p1, p2) * t * t + 2 * b(p1, p2) * t + c(p1); }
    return function (x) {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      var t = x;
      for (var i = 0; i < 8; i++) {
        var s = slope(t, x1, x2);
        if (Math.abs(s) < 1e-6) break;
        t -= (at(t, x1, x2) - x) / s;
      }
      return at(Math.min(1, Math.max(0, t)), y1, y2);
    };
  }

  var ease = {
    linear: function (t) { return t; },
    out: bezier(0.2, 0.7, 0.2, 1),
    inOut: bezier(0.65, 0, 0.35, 1),
    back: bezier(0.3, 1.4, 0.5, 1),
  };

  var DUR = { small: 220, travel: 420, scene: 2000 };

  /* tween(ms, onFrame(p), {ease}) -> Promise. Under reduced motion it jumps to p = 1. */
  function tween(ms, onFrame, opts) {
    opts = opts || {};
    var fn = opts.ease || ease.out;
    return new Promise(function (resolve) {
      if (reducedMotion() || !ms || !root.requestAnimationFrame) { onFrame(1); resolve(); return; }
      var start = null;
      function frame(now) {
        if (start === null) start = now;
        var p = Math.min(1, (now - start) / ms);
        onFrame(fn(p));
        if (p < 1) root.requestAnimationFrame(frame); else resolve();
      }
      root.requestAnimationFrame(frame);
    });
  }

  function wait(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, reducedMotion() ? 0 : ms); });
  }

  /* flip(container, mutate, {ms}): animate children of `container` (elements with
   * data-flip keys) from their old positions to the new ones after mutate(). */
  function flip(container, mutate, opts) {
    opts = opts || {};
    var ms = opts.ms === undefined ? DUR.small : opts.ms;
    var before = {};
    container.querySelectorAll("[data-flip]").forEach(function (node) {
      before[node.getAttribute("data-flip")] = node.getBoundingClientRect();
    });
    mutate();
    if (reducedMotion()) return Promise.resolve();
    var moves = [];
    container.querySelectorAll("[data-flip]").forEach(function (node) {
      var key = node.getAttribute("data-flip");
      var now = node.getBoundingClientRect();
      var old = before[key];
      if (!old) {
        node.animate([{ opacity: 0, transform: "translateY(-6px)" }, { opacity: 1, transform: "none" }],
          { duration: ms, easing: "cubic-bezier(.2,.7,.2,1)", fill: "backwards", delay: opts.stagger ? opts.stagger * moves.length : 0 });
        moves.push(node);
        return;
      }
      var dx = old.left - now.left, dy = old.top - now.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
      node.animate([{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "none" }],
        { duration: ms, easing: "cubic-bezier(.2,.7,.2,1)" });
      moves.push(node);
    });
    return wait(ms);
  }

  /* travel(node, fromRect, toRect, ms): move a node visually between two rects. */
  function travel(node, fromRect, toRect, ms) {
    if (reducedMotion() || !node.animate) return Promise.resolve();
    var dx = fromRect.left - toRect.left, dy = fromRect.top - toRect.top;
    var anim = node.animate([{ transform: "translate(" + dx + "px," + dy + "px)" }, { transform: "none" }],
      { duration: ms || DUR.travel, easing: "cubic-bezier(.2,.7,.2,1)" });
    return new Promise(function (resolve) { anim.onfinish = resolve; anim.oncancel = resolve; });
  }

  /* Mounting. */
  var registry = {};
  function register(name, mountFn) {
    registry[name] = mountFn;
    scan();
  }
  function scan() {
    if (typeof document === "undefined") return;
    document.querySelectorAll("code[data-a2-expr]").forEach(function (node) {
      if (node.hasAttribute("data-a2-expr-ready")) return;
      var rendered = expr(node.textContent, {
        given: (node.getAttribute("data-a2-given") || "").split(/[\s,]+/).filter(Boolean),
        invented: (node.getAttribute("data-a2-invented") || "").split(/[\s,]+/).filter(Boolean)
      });
      node.textContent = "";
      Array.from(rendered.childNodes).forEach(function (child) { node.appendChild(child); });
      node.classList.add("a2-expr");
      node.setAttribute("data-a2-expr-ready", "1");
    });
    document.querySelectorAll("[data-a2]").forEach(function (node) {
      var name = node.getAttribute("data-a2");
      if (!registry[name] || node.getAttribute("data-a2-ready")) return;
      node.setAttribute("data-a2-ready", "1");
      try {
        registry[name](node, A2.mock);
      } catch (err) {
        node.removeAttribute("data-a2-ready");
        if (root.console) root.console.error("A2 mount failed: " + name, err);
      }
    });
  }

  A2.KINDS = KINDS;
  A2.KINDS6 = KINDS6;
  A2.KIND6_META = KIND6_META;
  A2.kindOf = kindOf;
  A2.token = token;
  A2.copyAscii = copyAscii;
  A2.expr = expr;
  A2.legend = legend;
  A2.badge = badge;
  A2.hasRecordedScope = hasRecordedScope;
  A2.scopedBadge = scopedBadge;
  A2.runBadge = runBadge;
  A2.evidenceRecord = evidenceRecord;
  A2.chargedLeaves = chargedLeaves;
  A2.KIND_META = KIND_META;
  A2.STATUSES = STATUSES;
  A2.el = el;
  A2.append = append;
  A2.icon = icon;
  A2.kindBadge = kindBadge;
  A2.chip = chip;
  A2.value = value;
  A2.outcome = outcome;
  A2.formatValue = formatValue;
  A2.isCard = isCard;
  A2.isOutcome = isOutcome;
  A2.fieldNames = fieldNames;
  A2.listItems = listItems;
  A2.ALL_KINDS = ALL_KINDS;
  A2.boundary = boundary;
  A2.isOpened = isOpened;
  A2.pathKey = pathKey;
  A2.evidence = evidence;
  A2.scopeText = scopeText;
  A2.reducedMotion = reducedMotion;
  A2.ease = ease;
  A2.DUR = DUR;
  A2.tween = tween;
  A2.wait = wait;
  A2.flip = flip;
  A2.travel = travel;
  A2.register = register;
  A2.scan = scan;
  root.A2 = A2;
  register("legend", function (host) { host.appendChild(legend()); });

  if (typeof document !== "undefined") {
    if (document.readyState !== "loading") scan(); else document.addEventListener("DOMContentLoaded", scan);
    if (root.document$ && root.document$.subscribe) root.document$.subscribe(function () { scan(); });
  }
  if (typeof module !== "undefined" && module.exports) module.exports = A2;
})(typeof window !== "undefined" ? window : globalThis);
