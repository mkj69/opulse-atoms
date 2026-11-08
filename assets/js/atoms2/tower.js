(function (root) {
  "use strict";
  var A2 = root.A2;
  var FIELDS = ["domain", "modalities", "open_kinds", "star_kind", "reasoning", "state", "outcomes", "visibility", "agents", "scale", "difficulty", "uses"];
  var KINDS = A2.KINDS6;
  var NO_SOURCE = "No ASCII source published: the core printer cannot print this definition.";

  function ascii(value) {
    var content = String(value == null ? "" : value);
    return /^[\x20-\x7e]*$/.test(content) ? content.trim() : "notation pending from the worlds export";
  }
  function exportNotation(record, kind) {
    var notation = record && (record.ascii || record.decl || record.text);
    if (typeof notation !== "string" || !notation.trim() || !/^[\x20-\x7e]+$/.test(notation)) return null;
    if (notation.startsWith("comb @"))
      return /^comb @[A-Za-z_][A-Za-z_0-9]*\[.*\]\(.*\)/.test(notation) ? notation : null;
    if (((kind || record.kind) === "combinator" || notation.startsWith("@")) &&
        !/^@[A-Za-z_][A-Za-z_0-9]*\[.*\]\(.*\)$/.test(notation)) return null;
    return notation;
  }
  function entryKind(entry) {
    return entry.kind === "template" ? "object" : entry.kind;
  }
  function tags(world) {
    return world.tags || world.decl && world.decl.tags || {};
  }
  function tagField(world, field) {
    var data = tags(world);
    return Array.isArray(data) ? (field === "tags" ? data : null) : data[field];
  }
  function hasTags(world) {
    var data = tags(world);
    return Array.isArray(data) ? data.length > 0 : Object.keys(data).length > 0;
  }
  function openKinds(world) {
    var value = world.open_kinds || tagField(world, "open_kinds") || world.decl && world.decl.open_kinds;
    return Array.isArray(value) ? value : null;
  }
  function status(world) {
    return world.schema === "opulse.world_v2_export/1" && world.story && world.story.some(function (entry) {
      var evidence = entry.evidence || {};
      return A2.hasRecordedScope(evidence) && evidence.world_hash &&
        ["bounded", "exhaustive", "sampled"].includes(evidence.method) &&
        entry.examples && entry.examples.some(function (example) {
          return example.trace && example.outcome && typeof example.steps === "number";
      });
    }) ? "exported" : "design";
  }
  function tagValue(value) {
    if (Array.isArray(value)) return value.map(tagValue).join(", ");
    if (value && typeof value === "object") return Object.entries(value).map(function (pair) {
      return pair[0].replace(/_/g, " ") + ": " + tagValue(pair[1]);
    }).join("; ");
    return String(value);
  }
  function kindCounts(world) {
    var counts = {};
    KINDS.forEach(function (kind) { counts[kind] = 0; });
    (world.story || []).forEach(function (entry) {
      if (Object.prototype.hasOwnProperty.call(counts, entryKind(entry))) counts[entryKind(entry)]++;
    });
    return counts;
  }
  function dependencies(story, entry, decl) {
    var given = givenKinds(decl);
    return (entry.depends_on || []).map(function (name) {
      var base = name.split(".")[0];
      var invented = story.find(function (item) { return item.name === base; });
      return { name: name, row: invented && invented.layer, layer: invented && invented.def_layer,
        kind: invented ? entryKind(invented) : given[name] || given[base], invented: !!invented };
    });
  }
  function referencedDependencies(story, entry, decl) {
    var given = givenKinds(decl);
    var declaration = exportNotation(entry) || "";
    var recorded = entry.depends_on || [];
    return Object.keys(given).concat(story.map(function (item) { return item.name; }))
      .filter(function (name, index, all) {
        if (!name || name === entry.name || recorded.includes(name) || all.indexOf(name) !== index) return false;
        var escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        return new RegExp("(^|[^A-Za-z_0-9])" + escaped + "(?=$|[^A-Za-z_0-9])").test(declaration);
      }).map(function (name) {
        var invented = story.find(function (item) { return item.name === name; });
        return { name: name, row: invented && invented.layer, layer: invented && invented.def_layer,
          kind: invented ? entryKind(invented) : given[name], invented: !!invented };
      });
  }
  function givenKinds(decl) {
    var names = {};
    if (!decl) return names;
    [["object", decl.objects], ["operation", decl.operations],
      ["combinator", decl.combinators && decl.combinators.library],
      ["observation", decl.observation && decl.observation.probes],
      ["law", decl.laws], ["bridge", decl.bridges]].forEach(function (group) {
      (group[1] || []).forEach(function (item) {
        names[typeof item === "string" ? item : item.name] = group[0];
      });
    });
    return names;
  }
  function givenNames(decl) {
    var kinds = givenKinds(decl);
    return Object.keys(kinds).flatMap(function (name) {
      if (kinds[name] === "object") return [name, name.replace(/(^|_)([a-z])/g, function (_, separator, letter) {
        return letter.toUpperCase();
      })];
      if (kinds[name] === "combinator") return [name, name.startsWith("@") ? name : "@" + name];
      if (kinds[name] === "observation") return [name, name.startsWith("?") ? name : "?" + name];
      if (kinds[name] === "law") return [name, name.startsWith("#") ? name : "#" + name];
      if (kinds[name] === "bridge") return [name, name.startsWith("~") ? name : "~" + name];
      return [name];
    });
  }
  function scope(entry) {
    var evidence = entry.evidence || {};
    if (!A2.hasRecordedScope(evidence)) return "scope not recorded";
    return (evidence.scope && (evidence.scope.description || evidence.scope.domain) &&
      ascii(evidence.scope.description || evidence.scope.domain)) ||
      (evidence.scope && evidence.scope.size != null ? String(evidence.scope.size) + " cases" : "scope not recorded");
  }
  function hasTrace(example) {
    return !!(example && example.trace && (!example.trace.elided ||
      example.trace.children && example.trace.children.length));
  }
  function caseHeading(entry, example, index) {
    var heading = "RECORDED CASE " + (index + 1);
    if (entry.name === "safe_step") {
      var bot = example.inputs && example.inputs[0];
      var maze = bot && bot.f && bot.f[0] && bot.f[0].f && bot.f[0].f[0];
      var pose = example.learner_view && example.learner_view.pose;
      if (maze && maze.t === "str" && Array.isArray(pose) && pose.length === 3)
        heading += " / MAP " + ascii(maze.v) + " / FACING " + ascii(pose[2]) +
          " / POSE " + pose.map(ascii).join(",");
    } else if (example.learner_view && Array.isArray(example.learner_view.pose)) {
      heading += " / POSE " + example.learner_view.pose.map(ascii).join(",");
    }
    return heading + (Number.isSafeInteger(example.steps) ? " / " + example.steps + " RECORDED LAYER-0 STEPS" : " / STEP COUNT NOT RECORDED");
  }
  function differingField(left, right, path) {
    if (left === right) return null;
    if (left && right && typeof left === "object" && typeof right === "object") {
      var keys = Array.from(new Set(Object.keys(left).concat(Object.keys(right))));
      for (var key of keys) {
        var difference = differingField(left[key], right[key], path + (Array.isArray(left) ? "[" + key + "]" : "." + key));
        if (difference) return difference;
      }
      return null;
    }
    return { path: path, value: left };
  }
  function caseInputSummary(entry, example) {
    var inputs = example.inputs || [];
    if (entry.name === "safe_step") {
      var bot = inputs[0];
      var fields = bot && bot.t === "Bot" && bot.f;
      if (fields && fields.length >= 4) {
        var map = fields[0] && fields[0].f && fields[0].f[0];
        var facing = ["N", "E", "S", "W"][fields[3] && fields[3].v];
        if (map && map.t === "str" && facing)
          return "Bot: position (" + valueNotation(fields[1]) + ", " + valueNotation(fields[2]) +
            "), facing " + facing + ", maze " + ascii(map.v);
      }
    }
    var call = exportNotation(example);
    var other = (entry.examples || []).find(function (candidate) {
      return candidate !== example && exportNotation(candidate) === call;
    });
    if (!other) return null;
    var difference = differingField(inputs, other.inputs || [], "inputs");
    if (!difference) return "Inputs are identical in the export";
    var rendered = difference.value === undefined ? "missing" : valueNotation(difference.value);
    return "Recorded " + difference.path + ": " + ascii(rendered.length > 90 ? rendered.slice(0, 87) + "..." : rendered);
  }
  function casePurpose(entry, example) {
    if (example.demonstrates) return ascii(example.demonstrates);
    if (entry.name === "invert_gap") return "Inverse search for the first patterned seven-token word with three stars and gap 37, including the recorded search cost";
    if (entry.name === "cut_certificate") return "A recorded attempt to certify a minimum disconnecting cut on the given graph; this historical export has no checked 0.5 core trace";
    if (entry.name === "front_clear") return "A recorded front-clear probe on the supplied input; this exported case does not supply a real Bot state";
    var definition = exportNotation(entry) || "";
    var behavior = definition.includes(" = ") ? definition.split(" = ").slice(1).join(" = ").replace(/\s+L\d+$/, "") : "the declared " + entryKind(entry) + " " + identifier(entry);
    return (example.trace && example.trace.elided ? "Recorded outcome without a full trace for " : "Recorded result and layer-0 cost for ") +
      ascii(behavior.length > 145 ? behavior.slice(0, 142) + "..." : behavior);
  }
  function checkBadge(entry, href, decl, example) {
    var evidence = entry.evidence || {};
    if (!A2.hasRecordedScope(evidence)) return text("span", "scope not recorded", "w2-foot");
    var worldHash = decl && decl.lock && decl.lock.world_hash;
    var recordedTrace = example ? hasTrace(example) : (entry.examples || []).some(hasTrace);
    var label = recordedTrace ? "Historical export" : "Historical export (outcome only)";
    var description = label + ". " +
      "Recorded status: " + (entry.status || "not recorded") + ". Recorded scope: " + scope(entry) +
      ". Evidence world hash: " + (evidence.world_hash || "not recorded") +
      ". Stored export declaration lock hash: " + (worldHash || "not recorded") +
      ". Current declaration hash: not available in the browser (not recomputed).";
    var record = { evidence: Object.assign({}, evidence, { scope: Object.assign({}, evidence.scope, { description: description }) }),
      artifact: { file: href ? href.split("/").pop() : "worlds_v2 export", href: href, schema: "opulse.world_v2_export/1" } };
    var badge = A2.badge("design", { record: record });
    badge.textContent = label;
    badge.setAttribute("aria-label", badge.textContent + ". View evidence details");
    return badge;
  }
  function text(tag, value, className) {
    return A2.el(tag, { class: className || "", text: ascii(value) });
  }
  // The legend knows atoms by their stored name; the capitalized display identifier is only
  // the fallback when no mark exists.
  function chipText(entry, world) {
    return entry.kind === "template" || root.N3 && entry.name && root.N3.name(entry.name, world) ?
      entry.name : displayIdentifier(entry);
  }
  function pendingName(entry, world) {
    return A2.token(chipText(entry, world),
      { kind: entry.kind, origin: "invented", layer: entry.def_layer, world: world });
  }
  function identifier(entry) {
    var name = ascii(entry.name || "unnamed");
    var sigil = { combinator: "@", observation: "?", law: "#", bridge: "~" }[entry.kind] || "";
    return name.startsWith(sigil) ? name : sigil + name;
  }
  function displayIdentifier(entry) {
    if (entryKind(entry) !== "object") return identifier(entry);
    var declaration = [entry.ascii, entry.decl, entry.design_decl].find(function (value) {
      return typeof value === "string" && /^\s*obj\s+[A-Z][A-Za-z_0-9]*/.test(value);
    });
    var declared = declaration && /^\s*obj\s+([A-Z][A-Za-z_0-9]*)/.exec(declaration);
    if (declared) return declared[1];
    return identifier(entry).split("_").map(function (part) {
      return part.charAt(0).toUpperCase() + part.slice(1);
    }).join("");
  }
  var valueNotation = A2.formatValue;
  function safeValueNotation(value) {
    return value == null ? "not recorded" : valueNotation(value);
  }
  function recordedValue(label, value, given, forceDisclosure, world) {
    if (value == null || value === "") return text("p", "No " + label + " recorded", "w2-muted");
    if (value === SEALED) return text("p", SEALED, "w2-muted");
    var expression = typeof value === "string" ? A2.expr(value, { given: given, world: world }) : A2.value(value, { world: world });
    if (!forceDisclosure && (typeof value !== "string" || value.length <= 320)) return expression;
    return A2.el("details", { class: "w2-long-value" }, [
      text("summary", "Inspect recorded " + label + " (long value)"), expression]);
  }
  var SEALED = "sealed (judge-only)";
  function isSealedValue(value) {
    if (!value || typeof value !== "object") return false;
    if (["sealed_fixture", "judge_only_fixture", "redaction_marker", "redacted", "judge_only"].some(function (key) {
      return Object.prototype.hasOwnProperty.call(value, key) && value[key] !== false && value[key] != null;
    })) return true;
    return Object.values(value).some(isSealedValue);
  }
  function outcomeNotation(outcome) {
    if (!outcome) return "Unknown(unrecorded)";
    if (outcome.ok) {
      if (isSealedValue(outcome.ok)) return SEALED;
      var rendered = valueNotation(outcome.ok);
      if (rendered === "[object Object]" && typeof outcome.ok.repr === "string") rendered = ascii(outcome.ok.repr);
      if (rendered === "[object Object]" && typeof outcome.ok.elided_value === "string" &&
          Number.isSafeInteger(outcome.ok.chars))
        rendered = "elided(" + ascii(outcome.ok.elided_value) + ", " + outcome.ok.chars + " chars)";
      if (rendered.includes("[object Object]") || rendered.startsWith("{")) rendered = "value not available";
      return "Ok(" + rendered + ")";
    }
    if (outcome.bottom) return "Bottom(" + ascii(typeof outcome.bottom === "string" ? outcome.bottom : "reason not available") + ")";
    return "Unknown(" + ascii(typeof outcome.unknown === "string" ? outcome.unknown : "resource") + ")";
  }
  function traceLines(trace, lines, depth, exampleCall) {
    lines.push({ depth: depth, call: exportNotation(trace) || (depth === 0 ? exampleCall : null),
      name: trace.name, kind: trace.kind, outcome: isSealedValue(trace.outcome) ? SEALED : trace.outcome || null, steps: trace.steps,
      layer: trace.kind === "root" ? null : trace.layer, given: trace.given,
      elided: trace.elided });
    (trace.children || []).forEach(function (child) { traceLines(child, lines, depth + 1); });
    return lines;
  }
  function traceLabel(kind, hasAtom) {
    return hasAtom ? null : kind === "operation" ? "local loop" : "Recorded call";
  }
  function fieldChips(world, fields) {
    var group = A2.el("div", { class: "w2-tags" });
    (fields || FIELDS).forEach(function (field) {
      var value = field === "open_kinds" ? openKinds(world) : tagField(world, field);
      if (value == null || value === "") return;
      (Array.isArray(value) ? value : [value]).forEach(function (item) {
        group.appendChild(text("span", field.replace(/_/g, " ") + ": " + tagValue(item), "w2-tag"));
      });
    });
    if (Array.isArray(tags(world)) && tags(world).length && (!fields || fields.includes("domain") || fields.includes("tags")))
      tags(world).forEach(function (item) { group.appendChild(text("span", "tags: " + tagValue(item), "w2-tag")); });
    if (!hasTags(world))
      group.appendChild(text("span", "tags pending", "w2-tag w2-pending"));
    if (!openKinds(world)) group.appendChild(text("span", "open kinds pending", "w2-tag w2-pending"));
    return group;
  }
  function entryCard(entry, story, href, decl, worldName, parseStatus) {
    var card = A2.el("article", { class: "w2-step a2-k-" + entryKind(entry) });
    var given = givenNames(decl);
    card.appendChild(text("p", "Tower position: row " + (entry.layer == null ? story.indexOf(entry) + 1 : entry.layer), "w2-eyebrow"));
    var machineDeclaration = entry.ascii || entry.decl || entry.design_decl || "";
    var declaration = ascii(machineDeclaration);
    var designDeclaration = !!(entry.design_decl && machineDeclaration === entry.design_decl ||
      root.N3 && typeof root.N3.isDesign === "function" && root.N3.isDesign(machineDeclaration, worldName));
    var notation = !designDeclaration && root.N3 && root.N3.lookup(machineDeclaration, worldName);
    var declaredLayer = /\bL(\d+)\s*$/.exec(declaration);
    if (entry.def_layer != null) card.appendChild(text("p", declaredLayer && Number(declaredLayer[1]) !== entry.def_layer ?
      "Declared L" + declaredLayer[1] + ", computed layer " + entry.def_layer :
      "Definition layer: L" + entry.def_layer + " (computed)", "w2-eyebrow"));
    if (entry.kind === "template") card.appendChild(text("p", "Object template (parameterized definition)", "w2-eyebrow"));
    card.appendChild(A2.el("h3", {}, [pendingName(entry, worldName)]));
    card.appendChild(checkBadge(entry, href, decl));
    var examples = entry.examples || [];
    if (examples.length) {
      card.appendChild(text("p", "First recorded result", "w2-eyebrow"));
      card.appendChild(recordedValue("outcome", examples[0].outcome, given, false, worldName));
    }
    card.appendChild(text("p", "Recorded scope: " + scope(entry) + ".", "w2-foot"));
    if (notation) {
      if (notation.signature) card.appendChild(A2.expr(notation.signature.display, { world: worldName }));
      card.appendChild(A2.expr(machineDeclaration, { given: given, world: worldName }));
    } else if (!designDeclaration && root.N3 && root.N3.legend(worldName).length) {
      card.appendChild(text("p", NO_SOURCE, "w2-muted"));
    } else if (declaration) {
      var sourceStatus = parseStatus && parseStatus.entries[worldName + "/" + entry.name];
      if (sourceStatus === true && !designDeclaration) {
        if (declaration.length > 140) card.appendChild(A2.el("details", { class: "w2-long-value" }, [
          text("summary", "Inspect full ASCII source"), A2.expr(declaration, { given: given, world: worldName })]));
        else {
          card.appendChild(text("p", "ASCII source", "w2-eyebrow"));
          card.appendChild(A2.expr(declaration, { given: given, world: worldName }));
        }
      } else if (sourceStatus === "placeholder (core notation cannot encode this body)" && !designDeclaration) {
        if (declaration.length > 140) card.appendChild(A2.el("details", { class: "w2-long-value" }, [
          text("summary", sourceStatus), text("p", declaration, "w2-design-text")]));
        else {
          card.appendChild(text("p", sourceStatus, "w2-eyebrow"));
          card.appendChild(text("p", declaration, "w2-design-text"));
        }
      } else {
        if (declaration.length > 140) card.appendChild(A2.el("details", { class: "w2-long-value" }, [
          text("summary", "Inspect full design text (not notation v3 source)"), root.N3 || sourceStatus === undefined && !entry.design_decl ?
            A2.expr(machineDeclaration, { given: given, world: worldName, design: true }) : text("p", declaration, "w2-design-text")]));
        else {
          card.appendChild(text("p", "Design text (not notation v3 source)", "w2-eyebrow"));
          card.appendChild(root.N3 || sourceStatus === undefined && !entry.design_decl ?
            A2.expr(machineDeclaration, { given: given, world: worldName, design: true }) : text("p", declaration, "w2-design-text"));
        }
      }
    } else if (entry.body_sha256) {
      card.appendChild(text("p", NO_SOURCE, "w2-muted"));
    }
    var deps = dependencies(story, entry, decl);
    var referenced = referencedDependencies(story, entry, decl);
    var list = A2.el("div", { class: "w2-deps" });
    if (!deps.length) list.appendChild(text("span", referenced.length ?
      "No recorded depends_on edges; see declaration references below" : "No recorded dependencies", "w2-muted"));
    function appendDependency(parent, dep, referenced) {
      var mark = root.N3 && root.N3.name(dep.name, worldName, dep.kind);
      if (!mark) {
        parent.appendChild(A2.el("span", { class: "a2-design-name", text: dep.name }));
        return;
      }
      var atom = root.N3.legend(worldName).find(function (candidate) { return candidate.name === dep.name; });
      parent.appendChild(A2.token(dep.name, { kind: atom && atom.kind || dep.kind,
        origin: atom && atom.origin || (dep.invented ? "invented" : "given"),
        layer: atom && atom.layer != null ? atom.layer : dep.layer, world: worldName,
        title: dep.invented ? (referenced ? "References" : "Depends on") + " tower row " + dep.row : "Given at layer 0" }));
    }
    deps.forEach(function (dep) { appendDependency(list, dep, false); });
    card.appendChild(text("p", "Depends on", "w2-eyebrow"));
    card.appendChild(list);
    if (referenced.length) {
      card.appendChild(text("p", "Names referenced in declaration (not recorded depends_on edges)", "w2-eyebrow"));
      var referenceList = A2.el("div", { class: "w2-deps" });
      referenced.forEach(function (dep) {
        appendDependency(referenceList, dep, true);
      });
      card.appendChild(referenceList);
    }
    (entry.examples || []).forEach(function (example, index) {
      var box = A2.el("div", { class: "w2-case" });
      box.appendChild(text("h4", caseHeading(entry, example, index), "w2-case-heading"));
      box.appendChild(checkBadge(entry, href, decl, example));
      box.appendChild(text("p", "Demonstrates: " + casePurpose(entry, example) + ".", "w2-foot"));
      box.appendChild(text("p", "Recorded result and scope", "w2-foot"));
      box.appendChild(recordedValue("outcome", example.outcome, given, false, worldName));
      box.appendChild(text("p", "Recorded scope: " + scope(entry) + "." +
        (A2.hasRecordedScope(entry.evidence) ? " Open evidence details for status and hashes." : ""), "w2-foot"));
      box.appendChild(text("p", "Call and recorded inputs", "w2-foot"));
      var exampleCall = exportNotation(example);
      if (!exampleCall && typeof example.text === "string" && root.N3 &&
          typeof root.N3.isDesign === "function" && root.N3.isDesign(example.text, worldName))
        exampleCall = example.text;
      var callLine = A2.el("div", { class: "w2-call-line" });
      if (exampleCall && root.N3 && typeof root.N3.isDesign === "function" && root.N3.isDesign(exampleCall, worldName))
        box.appendChild(text("p", "Design text (not notation v3)", "w2-eyebrow"));
      callLine.appendChild(exampleCall ? A2.expr(exampleCall, { given: given, world: worldName }) : pendingName(entry, worldName));
      var inputSummary = caseInputSummary(entry, example);
      if (inputSummary) callLine.appendChild(text("span", inputSummary, "w2-input-summary"));
      box.appendChild(callLine);
      var inputLine = A2.el("div", { class: "w2-input-values" });
      inputLine.appendChild(text("span", "Inputs:", "w2-foot"));
      (example.inputs || []).forEach(function (input) { inputLine.appendChild(A2.value(input, { world: worldName })); });
      var collapseInputs = !!inputSummary || (typeof matchMedia === "function" && matchMedia("(max-width: 600px)").matches);
      box.appendChild(collapseInputs ? A2.el("details", { class: "w2-long-value" }, [
        text("summary", "Inspect recorded inputs"), inputLine]) : inputLine);
      if (example.trace && typeof example.trace.elided === "string" &&
          !example.trace.children?.length) {
        box.appendChild(text("p", "Trace not recorded (" + (example.steps == null ? "step count not recorded" : example.steps + " recorded layer-0 steps") + "). " +
          example.trace.elided, "w2-foot"));
      } else if (example.trace) {
        var details = A2.el("details", { class: "w2-trace" });
        var trace = traceLines(example.trace, [], 0, exampleCall);
        details.appendChild(text("summary", "Expand recorded trace steps (" + trace.length + " nodes)"));
        var steps = A2.el("ol");
        trace.forEach(function (step) {
          var item = A2.el("li", { class: "w2-trace-line" });
          item.style.setProperty("--trace-depth", Math.min(step.depth, 6));
          if (step.call) item.appendChild(A2.expr(step.call, { given: given, world: worldName }));
          else {
            if (step.name && step.kind !== "root") {
              var atom = root.N3 && root.N3.name(step.name, worldName, step.kind);
              var label = traceLabel(step.kind, atom);
              item.appendChild(label ? text("span", label, "w2-muted") : A2.token(chipText(step, worldName),
                { kind: step.kind, origin: step.given ? "given" : "invented", layer: step.layer, world: worldName }));
            }
          }
          item.appendChild(A2.el("span", { class: "a2-v-result w2-trace-outcome" },
            step.outcome == null ? text("span", "not recorded") :
              step.outcome === SEALED ? text("span", SEALED, "w2-muted") :
              typeof step.outcome === "string" ? A2.expr(step.outcome, { given: given, world: worldName }) :
                A2.value(step.outcome, { world: worldName })));
          item.appendChild(text("small", (step.given ? "Given / " : step.layer == null ? "" : "Definition layer " + step.layer + " / ") +
            (step.steps == null ? "step count not recorded" : step.steps + " steps"), "w2-foot"));
          if (step.elided > 0) item.appendChild(text("small", "+" + step.elided.toLocaleString("en-US") + " calls not shown", "w2-foot"));
          else if (typeof step.elided === "string" && step.elided.trim())
            item.appendChild(text("small", "Recorded trace note: " + step.elided, "w2-foot"));
          steps.appendChild(item);
        });
        details.appendChild(steps);
        box.appendChild(details);
      }
      card.appendChild(box);
    });
    return card;
  }
  function tower(container, world, href) {
    if (root.N3) {
      root.N3.register(world.notation3);
      container.appendChild(root.N3.legendPanel(world.world));
    }
    var story = world.story || [];
    if (!story.length) { container.appendChild(text("p", "No exported tower yet. Designed example.", "w2-muted")); return; }
    var rail = A2.el("div", { class: "w2-rail", role: "group", "aria-label": "Select a tower row" });
    var display = A2.el("div", { class: "w2-display", "aria-live": "polite" });
    function choose(index) {
      rail.querySelectorAll("button").forEach(function (button, position) {
        button.setAttribute("aria-pressed", String(index === position));
      });
      display.replaceChildren(entryCard(story[index], story, href, world.decl, world.world, world.parseStatus));
    }
    story.forEach(function (entry, index) {
      var button = A2.el("button", { type: "button", class: "w2-rail-button", "aria-pressed": "false" }, [
        text("small", "ROW " + (entry.layer == null ? index + 1 : entry.layer) +
          (entry.def_layer != null && /\bL(\d+)\s*$/.test(exportNotation(entry) || entry.decl || "") &&
            Number(/\bL(\d+)\s*$/.exec(exportNotation(entry) || entry.decl)[1]) !== entry.def_layer ?
            " / DECLARED " + /\bL(\d+)\s*$/.exec(exportNotation(entry) || entry.decl)[0] : "")),
        pendingName(entry, world.world)]);
      button.addEventListener("click", function () { choose(index); });
      rail.appendChild(button);
    });
    rail.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
      var buttons = Array.from(rail.querySelectorAll("button"));
      var index = buttons.indexOf(root.document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      var next = buttons[(index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length];
      next.focus(); next.click();
    });
    container.append(rail, display);
    choose(story.length - 1);
    if (root.requestAnimationFrame) root.requestAnimationFrame(function () {
      var selected = rail.querySelector('button[aria-pressed="true"]');
      rail.scrollLeft = selected.offsetLeft - rail.offsetLeft - (rail.clientWidth - selected.offsetWidth) / 2;
    });
  }
  A2.worlds = { fields: FIELDS, ascii: ascii, exportNotation: exportNotation, tags: tags, tagField: tagField, hasTags: hasTags, openKinds: openKinds, tagValue: tagValue, status: status,
    kindCounts: kindCounts, dependencies: dependencies, givenKinds: givenKinds, givenNames: givenNames, scope: scope, fieldChips: fieldChips, tower: tower, towerBadge: checkBadge,
    entryCard: entryCard, identifier: identifier, displayIdentifier: displayIdentifier, hasTrace: hasTrace, casePurpose: casePurpose, caseHeading: caseHeading, caseInputSummary: caseInputSummary,
    referencedDependencies: referencedDependencies,
    valueNotation: valueNotation, safeValueNotation: safeValueNotation, isSealedValue: isSealedValue, outcomeNotation: outcomeNotation, traceLines: traceLines, traceLabel: traceLabel, recordedValue: recordedValue };
  A2.tower = { kindCounts: kindCounts };
  A2.register("tower", function (mount) {
    mount.replaceChildren(A2.el("a", { href: "../../worlds/", text: "Explore the export-backed world catalogue" }));
  });
})(typeof window !== "undefined" ? window : globalThis);
