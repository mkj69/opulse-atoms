(function (root) {
  "use strict";
  var N3 = root.N3;
  var SUB = "₀₁₂₃₄₅₆₇₈₉", SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹";
  var OPS = "@#$&♠♤♥♡♦♢♣♧■□●○▲△▼▽◆◇★☆";
  var OBJECTS = "ABDEGHIJKLMOSTUVWXYZ", COMBS = "ΓΔΘΛΞΠΣΦΨΩ", HATS = "ÂĈÊĜĤÎĴÔŜÛŴŶẐ";
  var SIGNS = { add: "+", sub: "-", mul: "*", div: "/", mod: "%", eq: "==", ne: "!=", lt: "<", le: "<=", gt: ">", ge: ">=", and: "and", or: "or", not: "not" };
  var PRIORITY = { or: 1, and: 2, "==": 3, "!=": 3, "<": 3, "<=": 3, ">": 3, ">=": 3, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6 };
  var KEYWORDS = new Set("in let rec fail unknown memo prog entry jump halt fuel legacy if else and or not".split(" "));
  function digits(number, alphabet) { return String(number).replace(/[0-9]/g, function (digit) { return alphabet[Number(digit)]; }); }
  function variable(name) {
    if (!/^[a-z][A-Za-z0-9_]*$/.test(name) || KEYWORDS.has(name)) name += "_";
    return /^[a-z][A-Za-z0-9_]*$/.test(name) ? name : "v" + name.replace(/^_+/, "");
  }
  function atomName(name) { return name.replace(/^[@?#~]/, ""); }
  function arity(def) {
    if (def.arity != null) return def.arity;
    var spec = def.spec || {};
    if (def.kind === "combinator") return spec.params ? spec.params.length : def.params ? def.params.length - 1 : null;
    if (spec.inputs) return spec.inputs.length;
    return def.params ? def.params.length - (def.kind === "combinator" ? 1 : 0) : null;
  }
  function worldLegend(world, defs, library, value) {
    var registered = N3.legend(world);
    var base = registered.length ? registered.map(function (entry) { return Object.assign({}, entry); }) : [];
    var existing = new Set(base.map(function (entry) { return entry.kind + ":" + atomName(entry.name); }));
    var atoms = registered.length ? (library || []) : (defs || []).filter(function (item) { return item.world === world; }).concat(library || []);
    atoms = atoms.filter(function (item) { return item.world === world && !existing.has(item.kind + ":" + atomName(item.name)); });
    var observed = {};
    function visit(item) {
      if (Array.isArray(item)) { item.forEach(visit); return; }
      if (!item || typeof item !== "object") return;
      if (typeof item.t === "string" && typeof item.tag === "string") {
        (observed[item.t] || (observed[item.t] = [])).push(item.tag);
        (item.f || []).forEach(visit);
      } else Object.keys(item).forEach(function (key) { visit(item[key]); });
    }
    visit(value);
    base.forEach(function (entry) {
      if (entry.kind === "object" && (!entry.forms || !entry.forms.length) && observed[entry.name])
        entry.forms = Array.from(new Set(observed[entry.name]));
    });
    atoms = atoms.map(function (atom) {
      return atom.kind === "object" && (!atom.forms || !atom.forms.length) && observed[atom.name] ?
        Object.assign({}, atom, { forms: Array.from(new Set(observed[atom.name])) }) : atom;
    });
    atoms.sort(function (left, right) { return left.layer - right.layer; });
    var used = {}, counts = {}, overflow = {}, occupied = new Set(base.map(function (entry) { return entry.display; }));
    base.forEach(function (entry) {
      if (entry.layer === 0 && entry.origin === "given" && !/[₀₁₂₃₄₅₆₇₈₉]/.test(entry.display)) {
        var family = entry.kind === "object" ? (entry.mark || "").match(/^\\bb([A-Z])$/) : null;
        (used[entry.kind] || (used[entry.kind] = new Set())).add(family ? family[1] : Array.from(entry.display)[0]);
      }
      var match = entry.display.match(/[₀₁₂₃₄₅₆₇₈₉]+$/);
      if (match) {
        var index = Number(Array.from(match[0]).map(function (digit) { return SUB.indexOf(digit); }).join(""));
        if (entry.origin === "given") overflow[entry.kind] = Math.max(overflow[entry.kind] || 0, index);
        else counts[entry.kind] = Math.max(counts[entry.kind] || 0, index);
      }
    });
    atoms.forEach(function (atom) {
      var name = atomName(atom.name), kind = atom.kind, given = atom.origin === "given" || atom.layer === 0;
      var sign = given && kind === "operation" && SIGNS[name] && arity(atom) === (name === "not" ? 1 : 2) ? SIGNS[name] : null;
      var glyph, mark;
      if (sign) mark = "(" + sign + ")";
      else if (given) {
        var choices = kind === "operation" ? OPS : kind === "combinator" ? COMBS : kind === "observation" ? HATS : kind === "law" ? "≡" : kind === "bridge" ? "↝" : OBJECTS;
        if (kind === "object") choices = name.toLowerCase() === "int" ? "Z" + OBJECTS : name.toLowerCase() === "bool" ? "B" + OBJECTS.replace("B", "") : OBJECTS.replace(/[BZ]/g, "");
        glyph = Array.from(choices).find(function (candidate) { return !(used[kind] || new Set()).has(candidate); });
        if (glyph) { (used[kind] || (used[kind] = new Set())).add(glyph); mark = kind === "object" ? N3.toDisplay("\\bb" + glyph) : glyph; }
        else {
          var overflowGlyph = kind === "operation" ? "♦" : kind === "object" ? N3.toDisplay("\\bb" + Array.from(choices)[0]) : Array.from(choices)[0];
          do { overflow[kind] = (overflow[kind] || 0) + 1; mark = overflowGlyph + digits("0" + overflow[kind], SUB); }
          while (occupied.has(mark));
        }
      } else {
        var index = (counts[kind] || 0) + 1;
        var family = kind === "operation" ? arity(atom) === 1 ? "▼▲▽△" : arity(atom) === 2 ? "♦♠♥♣♢♤♡♧" : "■□●○◆◇★☆" : kind === "combinator" ? COMBS : kind === "law" ? "≡" : kind === "bridge" ? "↝" : kind === "observation" ? HATS : OBJECTS.replace(/[BZ]/g, "");
        glyph = Array.from(family)[(index - 1) % Array.from(family).length];
        mark = (kind === "object" ? N3.toDisplay("\\bb" + glyph) : glyph) + digits(index, SUB);
        while (occupied.has(mark)) { index++; mark = (kind === "object" ? N3.toDisplay("\\bb" + glyph) : glyph) + digits(index, SUB); }
        counts[kind] = index;
      }
      occupied.add(mark);
      base.push({ name: name, kind: kind, layer: atom.layer, origin: given ? "given" : "invented", display: mark, mark: N3.toAscii(mark), arity: arity(atom), forms: atom.forms || [] });
    });
    base.filter(function (atom) { return atom.kind === "object" && atom.forms && atom.forms.length > 1; }).forEach(function (object) {
      object.forms.forEach(function (tag) {
        // A capitalised form without declared fields is a constant, not a constructor atom.
        if (!(object.form_fields && object.form_fields[tag]) && /^[A-Z][A-Za-z0-9_]*$/.test(tag)) return;
        var name = object.name + "." + tag;
        if (base.some(function (entry) { return entry.name === name && entry.form_of === object.name; })) return;
        // Same rule as the Python legend: a constructor's family follows its declared field
        // count; forms known only from observed values have no declared count (n-ary family).
        var fields = object.form_fields && object.form_fields[tag] != null ? object.form_fields[tag] : null;
        var index = (counts.operation || 0) + 1;
        var family = fields === 1 ? "▼▲▽△" : fields === 2 ? "♦♠♥♣♢♤♡♧" : "■□●○◆◇★☆";
        var mark = Array.from(family)[(index - 1) % Array.from(family).length] + digits(index, SUB);
        while (occupied.has(mark)) { index++; mark = Array.from(family)[(index - 1) % Array.from(family).length] + digits(index, SUB); }
        counts.operation = index; occupied.add(mark);
        base.push({ name: name, kind: "operation", form_of: object.name, layer: object.layer,
          origin: object.origin, arity: fields, display: mark, mark: N3.toAscii(mark) });
      });
    });
    return base;
  }
  function convert(parsed, kind, world, defs, library) {
    var own = { world: world, kind: kind, name: parsed.name, layer: parsed.declaredLayer, origin: "invented", params: parsed.params };
    var active = (library || []).filter(function (entry) { return entry.world === world; });
    var known = active.some(function (entry) { return entry.kind === kind && atomName(entry.name) === atomName(parsed.name); }) ||
      N3.legend(world).some(function (entry) { return entry.kind === kind && atomName(entry.name) === atomName(parsed.name); });
    var atoms = worldLegend(world, defs, known ? active : active.concat([own])), byName = {};
    atoms.forEach(function (entry) { byName[atomName(entry.name)] = entry; });
    function lookup(name) { var found = byName[atomName(name)]; if (!found) throw Error("Unknown atom " + name); return found; }
    function expr(text, tag, precedence) { return { text: text, tag: tag, precedence: precedence || 0 }; }
    function operand(value, priority, right) {
      if (value.tag === "group") return value.text;
      if (value.tag === "bin" && (value.precedence < priority || right && value.precedence === priority) ||
          priority >= 8 && ["inf", "pre", "post", "bare"].includes(value.tag) ||
          priority && ["let", "cases"].includes(value.tag) || priority >= 8 && value.tag === "num" && value.text[0] === "-") return "(" + value.text + ")";
      return value.text;
    }
    var slots = {};
    if (kind === "combinator") slots[parsed.params[0]] = "♦ₐ";
    function call(name, args, observation, opCount) {
      var entry = byName[atomName(name)], mark = slots[name] || (entry && entry.display);
      if (!mark) throw Error("Unknown call " + name);
      var values = args.map(node), sign = entry && entry.kind === "operation" && /^\(.+\)$/.test(mark) ? mark.slice(1, -1) : null;
      if (entry && entry.kind === "combinator") {
        var count = opCount == null ? args.findIndex(function (arg) { return arg.node !== "Var" || !slots[arg.name] && !byName[arg.name]; }) : opCount;
        if (count < 0) count = args.length;
        var marks = args.slice(0, count).map(function (arg) { return slots[arg.name] || lookup(arg.name).display; });
        mark += "[" + marks.join(", ") + "]";
        values = values.slice(count);
        if (values.length === 1) return ["inf", "bin", "post", "pre", "let", "cases", "bare", "group"].includes(values[0].tag) ?
          expr(mark + " (" + values[0].text + ")", "call") : expr(mark + " " + values[0].text, "pre");
        if (values.length === 2) return expr(operand(values[0], 8) + " " + mark + " " + operand(values[1], 8), "inf");
        return expr(mark + "(" + values.map(function (value) { return value.text; }).join(", ") + ")", "call");
      }
      if (observation || entry && entry.kind === "observation") return expr(mark + "⟨" + (values.length ? values.map(function (value) { return value.text; }).join(", ") : kind === "observation" ? "s" : "") + "⟩", "call");
      if (entry && (entry.kind === "object" || entry.kind === "bridge")) return expr(mark + "(" + values.map(function (value) { return value.text; }).join(", ") + ")", "call");
      if (sign && values.length === 2) { var level = PRIORITY[sign]; return expr(operand(values[0], level) + " " + sign + " " + operand(values[1], level, true), "bin", level); }
      if (sign === "not" && values.length === 1) return expr("not " + operand(values[0], 3), "un");
      if (values.length === 1 && mark === "@") return expr(operand(values[0], 8) + " @", "post");
      if (values.length === 2) return expr(operand(values[0], 8) + " " + mark + " " + operand(values[1], 8), "inf");
      if (values.length === 1 && !["bin", "inf", "post", "pre", "let", "cases", "bare", "group"].includes(values[0].tag)) return expr(mark + " " + operand(values[0], 8), "pre");
      return expr(mark + (values.length === 1 && ["bin", "inf", "post", "pre"].includes(values[0].tag) ? " " : "") + "(" + values.map(function (value) { return value.text; }).join(", ") + ")", "call");
    }
    function node(value) {
      if (value.node === "Var") return expr(slots[value.name] || (byName[atomName(value.name)] && !parsed.params.includes(value.name) ? lookup(value.name).display : variable(value.name)), "var");
      if (value.node === "Lit") { var literal = N3.value(value.value, world); if (!literal) throw Error("Unsupported literal"); return expr(literal.display, "num"); }
      if (value.node === "Call") return call(value.fn, value.args, value.observation, value.opCount);
      if (value.node === "Not") return expr("not " + operand(node(value.operand), 3), "un");
      if (value.node === "And" || value.node === "Or") { var sign = value.node === "And" ? "and" : "or", level = PRIORITY[sign]; return expr(operand(node(value.left), level) + " " + sign + " " + operand(node(value.right), level, true), "bin", level); }
      if (value.node === "Test") return node(value.expr);
      if (value.node === "Let") return expr("let " + variable(value.name) + " = " + node(value.value).text + " in " + node(value.body).text, "let");
      if (value.node === "Case") {
        var arms = [], tail = value;
        while (tail && tail.node === "Case") {
          tail.arms.forEach(function (arm) { arms.push(node(arm[1]).text + ", if " + node(arm[0]).text); });
          tail = tail.default;
        }
        if (!tail) throw Error("Case without a default");
        arms.push(node(tail).text + ", else");
        return expr("{ " + arms.join("; ") + " }", "cases");
      }
      throw Error("Unsupported node " + value.node);
    }
    if (!byName.eq) byName.eq = { kind: "operation", display: "(==)" };
    if (!byName.neq) byName.neq = { kind: "operation", display: "(!=)" };
    var entry = lookup(parsed.name), mark = entry.display, params = parsed.params || [];
    var signature = null, head, body;
    if (kind === "operation") {
      head = call(parsed.name, params.map(function (name) { return { node: "Var", name: name }; })).text;
      signature = digits(parsed.declaredLayer, SUP) + mark + " : " + (params.length ? params.map(function () { return "ℤ"; }).join(" × ") : "()") + " → ℤ";
    } else if (kind === "combinator") {
      head = mark + "[♦ₐ] " + params.slice(1).map(variable).join(", ");
    } else if (kind === "observation") head = mark + "⟨s⟩";
    else if (kind === "object") head = mark;
    else if (kind === "law") {
      if (!params.length) throw Error("A law without binders has no display form");
      return checked({ signature: null, formula: mark + " : ∀ " + params.map(variable).join(", ") + " ∈ ℤ. " + node(parsed.body).text });
    } else if (kind === "bridge") { head = mark + "(x)"; signature = mark + " : ℤ → ℤ"; }
    else throw Error("Unsupported kind " + kind);
    if (parsed.refine) throw Error("Refine canonicalizer has no world mark");
    body = node(parsed.body).text;
    return checked({ signature: signature, formula: head + " = " + (kind === "object" ? "(" + body + ")" : "{ " + body + " }") });
  }
  function checked(result) {
    [result.signature, result.formula].filter(Boolean).forEach(function (text) { if (N3.toDisplay(N3.toAscii(text)) !== text) throw Error("Noncanonical notation v3"); });
    return result;
  }
  function value(input, world, defs, library) {
    var stored = N3.value(input, world);
    if (stored) return stored;
    var marks = worldLegend(world, defs, library, input);
    function convert(item) {
      var known = N3.value(item, world);
      if (known) return known.display;
      if (Array.isArray(item)) return "[" + item.map(convert).join(", ") + "]";
      if (!item || typeof item !== "object") throw Error("Unsupported value");
      if ("ok" in item) return convert(item.ok);
      if ("bottom" in item || "unknown" in item) {
        var failure = "bottom" in item ? "bottom" : "unknown";
        return (failure === "bottom" ? "fail" : "unknown") + "(" + convert(item[failure]) + ")";
      }
      if ((!item.f || !item.f.length) && /^[A-Z][A-Za-z0-9_]*$/.test(String(item.tag))) return String(item.tag);
      var entry = marks.find(function (atom) { return atom.kind === "object" && atom.name === item.t; });
      if (!entry || !Array.isArray(item.f)) throw Error("Unknown object sort");
      var form = entry.forms && entry.forms.length === 1 && entry.forms[0] === item.tag ? entry :
        marks.find(function (atom) { return atom.kind === "operation" && atom.form_of === item.t && atom.name === item.t + "." + item.tag; });
      if (!form) throw Error("Unknown constructor");
      var fields = item.f.map(convert);
      return form.display + "(" + fields.join(", ") + ")";
    }
    try { var display = convert(input); checked({ signature: null, formula: display }); return { display: display, ascii: N3.toAscii(display) }; }
    catch (error) { return null; }
  }
  function render(text) {
    try { if (N3.toDisplay(N3.toAscii(text)) !== text) throw Error("Noncanonical notation v3"); return N3.render(text, N3.toAscii(text)); }
    catch (error) { var code = document.createElement("code"); code.textContent = "No display form for this construct yet: " + text; return code; }
  }
  function preview(parsed, kind, world, defs, library, machine) {
    try { return convert(parsed, kind, world, defs, library); }
    catch (error) { return { signature: null, formula: null, fallback: "No display form for this construct yet", machine: machine }; }
  }
  root.N3Convert = { worldLegend: worldLegend, convert: convert, preview: preview, value: value, render: render };
  if (typeof module !== "undefined" && module.exports) module.exports = root.N3Convert;
})(typeof window !== "undefined" ? window : globalThis);
