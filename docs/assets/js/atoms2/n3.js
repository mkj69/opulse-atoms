(function (root) {
  "use strict";
  var SUB = Array.from("₀₁₂₃₄₅₆₇₈₉"), SUP = Array.from("⁰¹²³⁴⁵⁶⁷⁸⁹");
  var LETTERS = Array.from("ₐₑₒₓₕₖₗₘₙₚₛₜᵢⱼᵣᵤᵥ");
  var LETTER_NAMES = "aeoxhklmnpstijruv";
  var families = {};
  function family(names, glyphs, kind) {
    names.split(" ").forEach(function (name, index) { families[name] = { glyph: Array.from(glyphs)[index], kind: kind }; });
  }
  family("spade wspade heart wheart dia wdia club wclub sq wsq dot wdot up wup dn wdn lz wlz st wst",
    "♠♤♥♡♦♢♣♧■□●○▲△▼▽◆◇★☆", "operation");
  var bmp = { C: "ℂ", H: "ℍ", N: "ℕ", P: "ℙ", Q: "ℚ", R: "ℝ", Z: "ℤ" };
  Array.from("ABCDEFGHIJKLMNOPQRSTUVWXYZ").forEach(function (letter, index) {
    families["bb" + letter] = { glyph: bmp[letter] || String.fromCodePoint(0x1D538 + index), kind: "object" };
  });
  family("Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega", "ΓΔΘΛΞΠΣΦΨΩ", "combinator");
  family("hatA hatC hatE hatG hatH hatI hatJ hatO hatS hatU hatW hatY hatZ", "ÂĈÊĜĤÎĴÔŜÛŴŶẐ", "observation");
  family("eqv", "≡", "law");
  family("squig Squig", "↝⇝", "bridge");
  var glyphNames = {};
  Object.keys(families).forEach(function (name) { glyphNames[families[name].glyph] = name; });
  var punct = [
    ["⇒", "=>"], ["==", "=="], ["!=", "!="], ["<=", "<="], [">=", ">="],
    ["↦", "|->"], ["→", "->"], ["⊢", "|-"], ["⟨", "<|"], ["⟩", "|>"],
    ["⌜", "[|"], ["⌝", "|]"], ["⌞", "{|"], ["⌟", "|}"], ["…", "..."],
    ["×", "\\x"], ["∈", "\\in"], ["∀", "\\all"], ["∣", "\\mid"],
    ["↾", "\\seal"], ["↓", "\\dec"], ["⊤", "\\top"], ["⊥", "\\bot"],
    [":=", ":="],
    ...Array.from("=<>+-*/%()[]{},;:.?").map(function (value) { return [value, value]; })
  ];
  var allowed = new Set();
  Object.keys(families).forEach(function (name) { Array.from(families[name].glyph).forEach(function (c) { allowed.add(c); }); });
  Array.from(SUB.concat(SUP, LETTERS, Array.from("′⟨⟩⌜⌝⌞⌟⇒→↦⊢…×∈∀∣↾↓⊤⊥◈"))).forEach(function (c) { allowed.add(c); });
  var keywords = new Set("let in rec memo fail unknown prog entry jump halt fuel legacy if else and or not".split(" "));
  function digits(source, symbols) { return Array.from(source).map(function (c) { return symbols[Number(c)]; }).join(""); }
  function number(source, symbols) { return Array.from(source).map(function (c) { return String(symbols.indexOf(c)); }).join(""); }
  function markAt(text, start) {
    var rest = text.slice(start), layer = "", prefix = "", match;
    if ((match = rest.match(/^[⁰¹²³⁴⁵⁶⁷⁸⁹]+/))) { layer = number(match[0], SUP); prefix = match[0]; }
    else if ((match = rest.match(/^\^([0-9]+)(?=[\\@#$&])/))) { layer = match[1]; prefix = match[0]; }
    var index = start + prefix.length, glyph = Array.from(text.slice(index))[0], name = glyphNames[glyph];
    var kindNumber = "";
    if (name) index += glyph.length;
    else if ("@#$&".includes(glyph || "") && glyph) { name = glyph; index++; }
    else if (glyph === "◈") {
      match = text.slice(index + 1).match(/^[⁰¹²³⁴⁵⁶⁷⁸⁹]+/);
      if (!match) throw Error("◈ needs a kind number");
      kindNumber = number(match[0], SUP); name = "k" + kindNumber; index += 1 + match[0].length;
    } else if ((match = text.slice(index).match(/^\\(k[0-9]+|[A-Za-z]+)/)) &&
      (families[match[1]] || /^k[0-9]+$/.test(match[1]))) {
      name = match[1]; kindNumber = name.startsWith("k") ? name.slice(1) : ""; index += match[0].length;
    } else { if (layer) throw Error("layer without mark"); return null; }
    var suffix = "", asciiSuffix = "", displaySuffix = "", slot = false;
    if ((match = text.slice(index).match(/^[₀₁₂₃₄₅₆₇₈₉]+/))) {
      suffix = match[0]; asciiSuffix = "_" + Array.from(suffix).map(function (digit) { return SUB.indexOf(digit); }).join(""); displaySuffix = suffix;
    } else if (LETTERS.includes(Array.from(text.slice(index))[0])) {
      var first = Array.from(text.slice(index))[0];
      match = text.slice(index + first.length).match(/^[₀₁₂₃₄₅₆₇₈₉]*/);
      suffix = first + match[0]; slot = true;
      asciiSuffix = "_" + LETTER_NAMES[LETTERS.indexOf(first)] + number(match[0], SUB); displaySuffix = suffix;
    } else if ((match = text.slice(index).match(/^_([0-9]+|[a-z][0-9]*)/))) {
      suffix = match[0]; asciiSuffix = suffix; slot = !/^[0-9]/.test(match[1]);
      displaySuffix = slot ? LETTERS[LETTER_NAMES.indexOf(match[1][0])] + digits(match[1].slice(1), SUB) : digits(match[1], SUB);
      if (slot && displaySuffix.includes("undefined")) throw Error("bad slot index");
    } else if (text.startsWith("⌞", index) || text.startsWith("{|", index)) {
      suffix = text.startsWith("⌞", index) ? "⌞" : "{|";
      asciiSuffix = "{|"; displaySuffix = "⌞";
    }
    if (/^_0(?:$|[^0-9])/.test(asciiSuffix) || /^_00/.test(asciiSuffix)) throw Error("bad numbered given index");
    index += suffix.length;
    var prime = "";
    if (asciiSuffix !== "{|" && (text[index] === "′" || text[index] === "'")) { prime = text[index]; index++; }
    var base = families[name];
    return { type: "MARK", kind: base ? base.kind : kindNumber ? "kind" + kindNumber : "operation",
      start: start, end: index, text: text.slice(start, index), slot: slot, given: !asciiSuffix || /^_0[1-9]/.test(asciiSuffix),
      layer: !!layer, ascii: (layer ? "^" + layer : "") + (base ? "\\" + name : kindNumber ? "\\k" + kindNumber : name) + asciiSuffix + (prime ? "'" : ""),
      display: (layer ? digits(layer, SUP) : "") + (base ? base.glyph : kindNumber ? "◈" + digits(kindNumber, SUP) : name) + displaySuffix + (prime ? "′" : "") };
  }
  function lex(text) {
    text = String(text); var tokens = [], index = 0;
    while (index < text.length) {
      if (/\s/.test(text[index])) { index++; continue; }
      var mark = markAt(text, index);
      if (mark) { tokens.push(mark); index = mark.end; continue; }
      var rest = text.slice(index), match, type, ascii = null, display = null;
      if ((match = rest.match(/^"(?:[\x20-\x21\x23-\x5b\x5d-\x7e]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/))) {
        type = "STR";
      } else if ((match = rest.match(/^[A-Z][A-Za-z0-9_]*/))) type = "CONST";
      else if ((match = rest.match(/^[a-z][A-Za-z0-9_]*/))) type = keywords.has(match[0]) ? match[0] : "VAR";
      else if ((match = rest.match(/^[0-9]+/))) type = "NUM";
      else {
        var choice = punct.reduce(function (best, pair) {
          return pair.reduce(function (found, spelling) {
            return rest.startsWith(spelling) && (!found || spelling.length > found.spelling.length) ?
              { spelling: spelling, pair: pair } : found;
          }, best);
        }, null);
        if (!choice) throw Error("bad character " + JSON.stringify(Array.from(rest)[0]) + " at " + index);
        match = [choice.spelling]; type = choice.pair[1]; ascii = choice.pair[1]; display = choice.pair[0];
      }
      tokens.push({ type: type, start: index, end: index + match[0].length, text: match[0],
        ascii: ascii || match[0], display: display || match[0], kind: type === "NUM" ? "num" : type === "STR" ? "str" : keywords.has(type) ? "kw" : null });
      index += match[0].length;
    }
    return tokens;
  }
  function respell(text, spelling) {
    var end = 0, result = "", previous = null;
    lex(text).forEach(function (token) {
      var gap = text.slice(end, token.start);
      if (spelling === "ascii" && previous && previous.type === "MARK" && previous.ascii.endsWith("{|")) gap = " " + gap;
      if (spelling === "ascii" && token.ascii === "|}" && token.text === "⌟") gap += " ";
      if (spelling === "display" && previous && previous.type === "MARK" && previous.ascii.endsWith("{|")) gap = gap.replace(/^ /, "");
      if (spelling === "display" && token.ascii === "|}") gap = gap.replace(/ $/, "");
      result += gap + token[spelling]; end = token.end; previous = token;
    });
    return result + text.slice(end);
  }
  var worlds = Object.create(null);
  function register(block) {
    if (!block || !block.worlds) return;
    Object.keys(block.worlds).forEach(function (world) {
      var incoming = block.worlds[world], previous = worlds[world];
      if (!previous) { worlds[world] = incoming; return; }
      var entries = (previous.legend || []).filter(function (entry) {
        return !(incoming.legend || []).some(function (newEntry) {
          return newEntry.name === entry.name && newEntry.kind === entry.kind;
        });
      });
      worlds[world] = Object.assign({}, previous, incoming, {
        legend: entries.concat(incoming.legend || []),
        formulas: Object.assign({}, previous.formulas, incoming.formulas),
        prose: Object.assign({}, previous.prose, incoming.prose),
        designs: Array.from(new Set((previous.designs || []).concat(incoming.designs || [])))
      });
    });
  }
  function isDesign(text, world) {
    if (world !== undefined) return !!(worlds[world] && Array.isArray(worlds[world].designs) && worlds[world].designs.indexOf(text) !== -1);
    return Object.keys(worlds).some(function (key) { return isDesign(text, key); });
  }
  function lookup(text, world) {
    if (world !== undefined) return worlds[world] && worlds[world].formulas && worlds[world].formulas[text] || null;
    var matches = Object.keys(worlds).map(function (key) { return worlds[key].formulas && worlds[key].formulas[text]; }).filter(Boolean);
    return matches.length && matches.every(function (entry) { return entry.display === matches[0].display; }) ? matches[0] : null;
  }
  function prose(text, world) { return worlds[world] && worlds[world].prose && worlds[world].prose[text] || null; }
  function legend(world) { return worlds[world] && worlds[world].legend || []; }
  function pair(display) {
    try {
      var ascii = respell(display, "ascii");
      return respell(ascii, "display") === display ? { display: display, ascii: ascii } : null;
    } catch (error) { return null; }
  }
  function name(text, world, kind) {
    if (typeof text !== "string") return null;
    var bare = text.replace(/^[@?#~]/, "");
    var pool = world === undefined ? Object.keys(worlds).reduce(function (all, key) {
      return all.concat(legend(key));
    }, []) : legend(world);
    var entries = pool.filter(function (entry) {
      return (entry.name === text || entry.name.replace(/^[@?#~]/, "") === bare) && (!kind || entry.kind === kind);
    });
    // Sort names are case-insensitive in the machine notation (Int / int, Str / str).
    if (!entries.length && (!kind || kind === "object")) entries = pool.filter(function (entry) {
      return entry.kind === "object" && entry.name.toLowerCase() === bare.toLowerCase();
    });
    return entries.length && entries.every(function (entry) { return entry.display === entries[0].display; }) ?
      pair(entries[0].display) : null;
  }
  function value(input, world) {
    function simpleValue(item) {
      if (item === null || typeof item !== "object" || Array.isArray(item)) return true;
      if ((item.t === "int" || item.t === "str") && "v" in item && !("tag" in item)) return true;
      if (item.t === "bool" && (item.tag === "true" || item.tag === "false") && (!item.f || !item.f.length)) return true;
      if (!("t" in item) && "ok" in item) return simpleValue(item.ok);
      return item.t === "List" && item.tag === "List";
    }
    function convert(item) {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        if (!("t" in item) && "ok" in item) return convert(item.ok);
        if (!("t" in item) && ("bottom" in item || "unknown" in item)) {
          var outcome = "bottom" in item ? "bottom" : "unknown";
          var reason = convert(item[outcome]);
          return reason === null ? null : (outcome === "bottom" ? "fail" : "unknown") + "(" + reason + ")";
        }
        if ((item.t === "int" || item.t === "str") && "v" in item && !("tag" in item)) return convert(item.v);
        if (typeof item.t !== "string" || !("tag" in item)) return null;
        if (item.t === "bool" && (item.tag === "true" || item.tag === "false") && (!item.f || !item.f.length))
          return item.tag === "true" ? "⊤" : "⊥";
        // A nullary capitalised form is a constant (E, P1, Metro), as in the Python converter.
        if ((!item.f || !item.f.length) && /^[A-Z][A-Za-z0-9_]*$/.test(String(item.tag))) return String(item.tag);
        var entry = legend(world).find(function (candidate) { return candidate.kind === "object" && candidate.name === item.t; });
        if (!entry || !Array.isArray(item.f)) return null;
        var form = entry.forms && entry.forms.length === 1 && entry.forms[0] === item.tag ? entry :
          legend(world).find(function (candidate) {
            return candidate.name === item.t + "." + item.tag && candidate.kind === "operation" && candidate.form_of === item.t;
          });
        if (!form) return null;
        var fields = item.f.map(convert);
        if (fields.some(function (field) { return field === null; })) return null;
        // Python printer rule: a call with one compound argument (a card) gets a space.
        var compound = fields.length === 1 && !simpleValue(item.f[0]);
        return form.display + (compound ? " (" : "(") + fields.join(", ") + ")";
      }
      if (Array.isArray(item)) {
        var elements = item.map(convert);
        return elements.some(function (element) { return element === null; }) ? null : "[" + elements.join(", ") + "]";
      }
      if (typeof item === "boolean") return item ? "⊤" : "⊥";
      if (typeof item === "number") return Number.isSafeInteger(item) ? String(item) : null;
      if (typeof item === "string") return JSON.stringify(item).replace(/[^\x20-\x7e]/g, function (character) {
        return Array.from(character).map(function (point) {
          var code = point.codePointAt(0);
          if (code <= 0xffff) return "\\u" + code.toString(16).padStart(4, "0");
          code -= 0x10000;
          return "\\u" + (0xd800 + (code >> 10)).toString(16) + "\\u" + (0xdc00 + (code & 1023)).toString(16);
        }).join("");
      });
      return null;
    }
    var display = convert(input);
    return display === null ? null : pair(display);
  }
  function render(display, ascii, opts) {
    opts = opts || {};
    var span = document.createElement("span"); span.className = "n3" + (opts.class ? " " + opts.class : "");
    span.setAttribute("data-n3-ascii", ascii);
    var end = 0;
    lex(display).forEach(function (token) {
      if (token.start > end) span.appendChild(document.createTextNode(display.slice(end, token.start)));
      var child = document.createElement("span");
      child.className = token.kind ? "n3-k-" + token.kind : "n3-punct";
      if (token.slot) child.className += " n3-slot";
      if (token.given) child.className += " n3-given";
      if (token.layer) child.className += " n3-layer";
      child.textContent = token.text; span.appendChild(child); end = token.end;
    });
    if (end < display.length) span.appendChild(document.createTextNode(display.slice(end)));
    return span;
  }
  function legendPanel(world) {
    var details = document.createElement("details"); details.className = "n3-legend";
    var summary = document.createElement("summary"), heading = document.createElement("h3");
    heading.textContent = "Legend"; summary.appendChild(heading); details.appendChild(summary);
    var table = document.createElement("table"), caption = document.createElement("caption");
    caption.textContent = "Marks in this world"; table.appendChild(caption);
    var head = document.createElement("thead"), header = document.createElement("tr");
    ["Mark", "Name", "Kind", "Signature"].forEach(function (label) {
      var cell = document.createElement("th"); cell.textContent = label; cell.setAttribute("scope", "col"); header.appendChild(cell);
    }); head.appendChild(header); table.appendChild(head);
    var body = document.createElement("tbody");
    legend(world).forEach(function (entry) {
      var row = document.createElement("tr"), signature = entry.signature || {};
      [entry.display, entry.name, entry.kind === "object" && entry.forms && entry.forms.length > 1 ?
        "object (forms: " + entry.forms.join(", ") + ")" :
        entry.note && /^constructor of /.test(entry.note) ? entry.kind + " (" + entry.note + ")" : entry.kind,
        signature.display || ""].forEach(function (value, index) {
        var cell = document.createElement("td");
        if (index === 0 && (entry.mark || entry.mark === null))
          cell.appendChild(render(value, entry.mark || value));
        else if (index === 3 && signature.ascii) cell.appendChild(render(value, signature.ascii));
        else cell.textContent = value;
        row.appendChild(cell);
      }); body.appendChild(row);
    }); table.appendChild(body); details.appendChild(table); return details;
  }
  var N3 = { lex: lex, toAscii: function (text) { return respell(text, "ascii"); },
    toDisplay: function (text) { return respell(text, "display"); },
    kindOfMark: function (token) {
      var mark = typeof token === "string" ? lex(token)[0] : token;
      return mark && mark.type === "MARK" ? mark.kind : null;
    },
    ALLOWED: allowed, register: register, lookup: lookup, isDesign: isDesign, name: name, value: value,
    prose: prose, legend: legend, worldIds: function () { return Object.keys(worlds); }, render: render, legendPanel: legendPanel };
  root.N3 = N3;
  if (typeof module !== "undefined" && module.exports) module.exports = N3;
})(typeof window !== "undefined" ? window : globalThis);
