(function (root) {
  "use strict";
  var A2 = root.A2 || (root.A2 = {});
  var el = A2.el;
  var examples = {
    operation: { good: "op multiply_preview(a, b) = if is_zero(b) then 0 else add(a, multiply_preview(a, dec(b))) L1", bad: "op unknown_mul(a, b) = missing(a, b) L1", fuel: "op loop(a) = loop(succ(a)) L1" },
    object: { good: "obj Byte83 = mod(339, 256) L1", bad: "obj BadByte = succ(missing) L1", refine: "obj PairRatio = refine {num: int, den: int} where neq(den, 0) canon reduce L1" },
    combinator: { good: "comb @twice_preview[f](x) = f(f(x)) L1", bad: "comb @broken_twice[f](x) = f(missing(x)) L1" },
    observation: { good: "obs ?clear_ahead = not ?front_wall{} and not ?front_water{} L1", bad: "obs ?bad_probe = not sealed_truth L1" },
    law: { good: "law #byte_shift(a) = eq(mod(add(a, 256), 256), mod(a, 256)) L1", bad: "law #bad_law(a) = missing(a) L1" },
    bridge: { good: "bridge ~to_byte(a) = mod(a, 256) L1", bad: "bridge ~bad_bridge(a) = missing(a) L1" },
  };
  var featured = {
    object: "obj ResiduePair = refine {num: int, den: int} where neq(den, 0) canon reduce L1",
    combinator: "comb @adjust_twice[f](x) = f(add(f(x), 17)) L1"
  };
  var help = { operation: "op name(a, b) = expression L1; Int inputs and output", object: "obj Name = expression L1; or refine {field: int} where predicate canon reduce L1", combinator: "comb @name[f](x) = expression L1; use @name[succ](11)", observation: "obs ?name = not ?front_wall{} and not ?front_water{} L1; use ?name{}", law: "law #name(a) = Bool expression L1", bridge: "bridge ~name(a) = Int expression L1" };

  function presetsFor(kind) {
    var writeOnly = kind === "law" || kind === "bridge";
    var choices = [{ label: "Example", source: featured[kind] || examples[kind].good }, { label: writeOnly ? "Different draft (parse only)" : "Unbound name", source: examples[kind].bad }];
    if (kind === "operation") choices.push({ label: "Fuel exhausted", source: examples[kind].fuel });
    if (kind === "combinator") choices.push({ label: "Four applications", source: "comb @fourfold[f](x) = f(f(f(f(x)))) L1" });
    if (kind === "object") choices.push({ label: "Modulo constant (case preview)", source: "obj Byte17123 = mod(17123, 256) L1" });
    if (kind === "observation") choices[1].label = "Sealed truth";
    if (!writeOnly && kind !== "object") choices.push({ label: "Sampled evidence", source: examples[kind].good, sampled: true });
    return choices;
  }

  function contentHash(text, kind, world, dependencies) {
    var bytes = Array.from(new TextEncoder().encode(JSON.stringify([text, kind, world, dependencies || []])));
    var bitLength = bytes.length * 8;
    bytes.push(128);
    while (bytes.length % 64 !== 56) bytes.push(0);
    for (var shift = 56; shift >= 0; shift -= 8) bytes.push(Math.floor(bitLength / 2 ** shift) & 255);
    var state = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var constants = [
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
      0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
      0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
      0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
      0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
      0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
    ];
    function rotate(value, count) { return (value >>> count) | (value << (32 - count)); }
    for (var offset = 0; offset < bytes.length; offset += 64) {
      var words = new Array(64);
      for (var index = 0; index < 16; index++) {
        var start = offset + index * 4;
        words[index] = (bytes[start] << 24 | bytes[start + 1] << 16 | bytes[start + 2] << 8 | bytes[start + 3]) >>> 0;
      }
      for (var next = 16; next < 64; next++) {
        var low = words[next - 15], high = words[next - 2];
        words[next] = (words[next - 16] + (rotate(low, 7) ^ rotate(low, 18) ^ low >>> 3) +
          words[next - 7] + (rotate(high, 17) ^ rotate(high, 19) ^ high >>> 10)) >>> 0;
      }
      var [first, second, third, fourth, fifth, sixth, seventh, eighth] = state;
      for (var round = 0; round < 64; round++) {
        var mix = (eighth + (rotate(fifth, 6) ^ rotate(fifth, 11) ^ rotate(fifth, 25)) +
          (fifth & sixth ^ ~fifth & seventh) + constants[round] + words[round]) >>> 0;
        var sum = ((rotate(first, 2) ^ rotate(first, 13) ^ rotate(first, 22)) +
          (first & second ^ first & third ^ second & third)) >>> 0;
        eighth = seventh; seventh = sixth; sixth = fifth; fifth = fourth + mix >>> 0;
        fourth = third; third = second; second = first; first = mix + sum >>> 0;
      }
      [first, second, third, fourth, fifth, sixth, seventh, eighth].forEach(function (value, position) {
        state[position] = state[position] + value >>> 0;
      });
    }
    return state.map(function (value) { return value.toString(16).padStart(8, "0"); }).join("");
  }

  function storeSession(library, record, detachedEvidence) {
    var previous = library.find(function (entry) { return entry.world === record.world && entry.name === record.name; });
    var changedContent = !!previous && previous.content_hash !== record.content_hash;
    var changedEvidence = !!previous && JSON.stringify(previous.evidence) !== JSON.stringify(record.evidence);
    if ((changedContent || changedEvidence) && previous.evidence) detachedEvidence.push({ world: previous.world, name: previous.name, content_hash: previous.content_hash, evidence: previous.evidence });
    var updated = library.filter(function (entry) { return entry.world !== record.world || entry.name !== record.name; }).map(function (entry) { return Object.assign({}, entry); }).concat(record);
    if (changedContent || changedEvidence) {
      var changed = [record.name], visited = {};
      while (changed.length) {
        var name = changed.shift();
        if (visited[name]) continue;
        visited[name] = true;
        updated.forEach(function (entry) {
          if (entry === record || entry.world !== record.world || !entry.depends_on || entry.depends_on.indexOf(name) < 0) return;
          if (entry.evidence) detachedEvidence.push({ world: entry.world, name: entry.name, content_hash: entry.content_hash, evidence: entry.evidence });
          entry.evidence = null;
          entry.contract = null;
          entry.status = "callable";
          entry.content_hash = contentHash(entry.source, entry.kind, entry.world, dependencyHashes(entry.depends_on, entry.world, updated));
          entry.id = entry.world + "@preview/" + entry.name + "/" + entry.content_hash;
          changed.push(entry.name);
        });
      }
    }
    return { library: updated, replaced: changedContent || changedEvidence };
  }

  function dependencyHashes(names, world, library) {
    return names.map(function (name) {
      var dependency = library.find(function (entry) { return entry.world === world && entry.name === name && entry.session; });
      return [name, dependency ? dependency.content_hash : "given"];
    });
  }

  function tokenize(text) {
    var tokens = [], pattern = /\s+|[@?#~]?[A-Za-z_][A-Za-z_0-9]*|\d+|!=|==|[(){}\[\]:,=]|./gy, match;
    while ((match = pattern.exec(text))) {
      if (/^\s+$/.test(match[0])) continue;
      var before = text.slice(0, match.index), line = before.split("\n");
      tokens.push({ value: match[0], line: line.length, column: line[line.length - 1].length + 1 });
    }
    tokens.push({ value: "<end>", line: text.split("\n").length, column: text.split("\n").pop().length + 1 });
    return tokens;
  }
  function parse(text, kind) {
    var tokens = tokenize(text || ""), index = 0;
    function peek() { return tokens[index].value; }
    function fail(message) { var token = tokens[index]; throw new Error("Line " + token.line + ", column " + token.column + ": " + message); }
    function take(value) { if (peek() !== value) fail("Expected '" + value + "', got '" + peek() + "'."); index++; }
    function identifier() { if (!/^[@?#~]?[A-Za-z_][A-Za-z_0-9]*$/.test(peek()) || ["if", "then", "else", "let", "in", "not", "and", "or"].indexOf(peek()) >= 0) fail("Expected a name."); return tokens[index++].value; }
    function atom() {
      if (peek() === "not") { index++; return { node: "Not", operand: atom() }; }
      if (peek() === "(") { index++; var inner = expression(); take(")"); return inner; }
      if (/^\d+$/.test(peek())) { var number = Number(tokens[index++].value); if (!Number.isSafeInteger(number)) fail("Integer literal exceeds the safe range."); return { node: "Lit", value: { t: "int", v: number } }; }
      var position = tokens[index], name = identifier();
      if (name[0] === "@") {
        take("["); var operations = [];
        do { operations.push({ node: "Var", name: identifier() }); if (peek() !== ",") break; index++; } while (true);
        take("]"); take("("); var values = [];
        if (peek() !== ")") { do { values.push(expression()); if (peek() !== ",") break; index++; } while (true); }
        take(")"); return { node: "Call", fn: name, args: operations.concat(values), opCount: operations.length, line: position.line, column: position.column };
      }
      if (name[0] === "?" && peek() === "{") { index++; var observedArgs = []; if (peek() !== "}") observedArgs.push(expression()); take("}"); return { node: "Call", fn: ["?front_wall", "?front_water", "?front_free"].indexOf(name) >= 0 ? name.slice(1) : name, args: observedArgs, observation: true, line: position.line, column: position.column }; }
      if (name[0] === "?") fail("Use ?name{...} to read an observation.");
      if (peek() === "(") {
        index++; var args = [];
        if (peek() !== ")") { do { args.push(expression()); if (peek() !== ",") break; index++; } while (true); }
        take(")"); return { node: "Call", fn: name, args: args, line: position.line, column: position.column };
      }
      return { node: "Var", name: name };
    }
    function comparison() { return atom(); }
    function conjunction() { var left = comparison(); while (peek() === "and") { index++; left = { node: "And", left: left, right: comparison() }; } return left; }
    function disjunction() { var left = conjunction(); while (peek() === "or") { index++; left = { node: "Or", left: left, right: conjunction() }; } return left; }
    function expression() {
      if (peek() === "if") { index++; var condition = disjunction(); take("then"); var yes = expression(); take("else"); return { node: "Case", arms: [[{ node: "Test", expr: condition }, yes]], default: expression() }; }
      if (peek() === "let") { index++; var name = identifier(); take("="); var value = expression(); take("in"); return { node: "Let", name: name, value: value, body: expression() }; }
      return disjunction();
    }
    var prefix = { object: "obj", operation: "op", combinator: "comb", observation: "obs", law: "law", bridge: "bridge" }[kind];
    if (["obj", "op", "comb", "obs", "law", "bridge"].indexOf(peek()) >= 0 && peek() !== prefix) fail("Expected '" + prefix + "' declaration.");
    if (peek() === prefix) index++;
    var name = identifier(), params = [];
    var requiredSigil = { combinator: "@", observation: "?", law: "#", bridge: "~" }[kind] || "";
    if (name[0] !== requiredSigil && /[@?#~]/.test(name[0]) || requiredSigil && name[0] !== requiredSigil) fail("Use the ASCII sigil for this kind.");
    if (kind === "combinator") { take("["); do { params.push(identifier()); if (peek() !== ",") break; index++; } while (true); take("]"); take("("); if (peek() !== ")") { do { params.push(identifier()); if (peek() !== ",") break; index++; } while (true); } take(")"); }
    else if (peek() === "(") { index++; if (peek() !== ")") { do { params.push(identifier()); if (peek() !== ",") break; index++; } while (true); } take(")"); }
    if (new Set(params).size !== params.length) fail("Parameter names must be unique.");
    take("="); var refine = null, body;
    if (kind === "object" && peek() === "refine") {
      index++; take("{"); var fields = {};
      do { var field = identifier(); take(":"); fields[field] = identifier(); if (peek() !== ",") break; index++; } while (true);
      take("}"); take("where"); var valid = expression(); take("canon");
      var canon = identifier(); if (canon === "mod") { if (peek() !== "12") fail("Only mod 12 is available."); index++; canon = "mod 12"; }
      if (["reduce", "mod 12"].indexOf(canon) < 0) fail("Choose canon reduce or mod 12.");
      refine = { fields: fields, valid: valid, canon: canon }; body = null;
    } else body = expression();
    if (!/^L\d+$/.test(peek())) fail("Expected a declared layer L<n>.");
    var declaredLayer = Number(tokens[index++].value.slice(1));
    if (!Number.isSafeInteger(declaredLayer)) fail("Layer exceeds the safe range.");
    if (peek() !== "<end>") fail("Unexpected '" + peek() + "'.");
    if (kind === "observation" && params.length) throw new Error("Line 1, column 1: Observations do not take parameters.");
    return { name: name, params: params, body: body, refine: refine, declaredLayer: declaredLayer };
  }

  function check(parsed, kind, world, library, options) {
    library = library || []; options = options || {}; var mock = A2.mock || { defs: [], worlds: {} }, worldData = mock.worlds && mock.worlds[world] || {};
    var worldAtoms = (mock.defs || []).filter(function (item) { return item.world === world; });
    var previous = library.find(function (item) { return item.world === world && item.name === parsed.name; });
    if (worldAtoms.some(function (item) { return item.name === parsed.name; }) || previous && (!previous.session || previous.kind !== kind)) throw new Error("'" + parsed.name + "' already names a world or session atom.");
    if (options.reference && (options.reference === parsed.name || options.reference === "reference " + parsed.name)) throw new Error("A definition cannot use itself as a reference.");
    var available = worldAtoms.concat(library.filter(function (item) { return item.world === world && item.name !== parsed.name; }));
    var lookup = {}; available.forEach(function (item) { lookup[item.name] = item; });
    if (options.reference) {
      var referenceName = options.reference === "reference mul" ? "mul" : options.reference;
      if (!lookup[referenceName] || lookup[referenceName].kind !== kind) throw new Error("Reference '" + referenceName + "' must be a " + kind + " in this world.");
      var reference = lookup[referenceName];
      var referenceArity = (reference.spec.inputs || reference.spec.params || []).length + (reference.spec.op_params || []).length;
      if (referenceArity !== parsed.params.length) throw new Error("Reference '" + referenceName + "' has a different signature.");
    }
    var deps = [], slot = kind === "combinator" ? parsed.params[0] : null, reads = [];
    if (kind === "combinator" && parsed.params.length < 2) throw new Error("A combinator needs an operation slot and a value.");
    if (kind === "object" && parsed.params.length) throw new Error("An object is a constant or a refine declaration, not a function.");
    function visit(node, bound) {
      if (!node) return;
      if (node.node === "Let") { visit(node.value, bound); visit(node.body, bound.concat(node.name)); return; }
      if (node.node === "Var") {
        if (node.name === slot) throw new Error("Operation slot '" + slot + "' must be called, not used as a value.");
        if (bound.indexOf(node.name) >= 0) return;
        if (lookup[node.name]) {
          if (kind === "observation" && lookup[node.name].kind !== "observation") throw new Error("This browser preview supports only probes and observations as observation dependencies; the 0.5 core also permits pure definitions on observed values.");
          if (lookup[node.name].kind === "observation") {
            throw new Error("Read the observation with ?" + node.name.replace(/^\?/, "") + "{}.");
          }
          if (deps.indexOf(node.name) < 0) deps.push(node.name);
          return;
        }
        throw new Error((node.name === "sealed_truth" ? "Sealed truth is not a granted probe: " : "Unbound name ") + "'" + node.name + "'.");
      }
      if (node.node === "Call") {
        if ((node.fn === "eq" || node.fn === "neq") && node.args.length !== 2) throw new Error("Line " + node.line + ", column " + node.column + ": '" + node.fn + "' expects exactly two arguments.");
        var target = lookup[node.fn];
        if (node.fn === parsed.name) { if (kind !== "operation") throw new Error("Only operations may recurse in this preview."); if (node.args.length !== parsed.params.length) throw new Error("Recursive call has wrong arity."); }
        else if (node.fn === slot) { if (node.args.length !== 1) throw new Error("Slot '" + slot + "' needs one argument."); }
        else if (!target && ["eq", "neq"].indexOf(node.fn) < 0) throw new Error("Unbound call '" + node.fn + "'.");
        else if (target) {
          if (target.kind === "observation" && node.observation) {
            var channels = target.origin === "given" ? [target.name] : target.spec && target.spec.reads || [];
            channels.forEach(function (channel) { if (reads.indexOf(channel) < 0) reads.push(channel); });
          } else if (target.kind !== "operation" && target.kind !== "combinator") throw new Error("'" + node.fn + "' is not callable.");
          if (kind === "observation" && target.kind !== "observation") throw new Error("This browser preview supports only probes and observations as observation dependencies; the 0.5 core also permits pure definitions on observed values.");
          var count = target.spec && (target.spec.params || target.spec.inputs) || [];
          if (node.args.length !== count.length + (target.kind === "combinator" ? (target.spec.op_params || []).length : 0)) throw new Error("'" + node.fn + "' has wrong arity.");
          if (target.kind === "combinator" && node.opCount !== (target.spec.op_params || []).length) throw new Error("Use @name[ops](args) for combinators.");
          if (deps.indexOf(node.fn) < 0) deps.push(node.fn);
        }
        if (node.fn === slot && (node.opCount || node.observation)) throw new Error("Operation slots use f(value).");
        node.args.forEach(function (arg, position) {
          if (target && target.kind === "combinator" && position < (target.spec.op_params || []).length) {
            if (arg.node !== "Var" || !(arg.name === slot || lookup[arg.name] && lookup[arg.name].kind === "operation")) throw new Error("Slot " + (position + 1) + " of '" + node.fn + "' needs an operation name.");
            if (lookup[arg.name] && deps.indexOf(arg.name) < 0) deps.push(arg.name);
          } else visit(arg, bound);
        }); return;
      }
      if (node.node === "Lit") return;
      if (node.node === "Case") { node.arms.forEach(function (arm) { visit(arm[0], bound); visit(arm[1], bound); }); visit(node.default, bound); return; }
      ["left", "right", "operand", "expr"].forEach(function (key) { if (node[key]) visit(node[key], bound); });
    }
    if (parsed.refine) {
      Object.keys(parsed.refine.fields).forEach(function (field) {
        var sort = parsed.refine.fields[field];
        var objectName = sort === "int" ? "Int" : sort;
        if (!lookup[objectName] || lookup[objectName].kind !== "object" || lookup[objectName].spec.sort !== sort) throw new Error("Unknown object sort '" + sort + "'.");
      });
      if (parsed.refine.canon === "reduce" && !parsed.refine.fields.den) throw new Error("Reduce needs a den field.");
      visit(parsed.refine.valid, Object.keys(parsed.refine.fields));
      Object.keys(parsed.refine.fields).forEach(function (field) { var name = parsed.refine.fields[field] === "int" ? "Int" : parsed.refine.fields[field]; if (deps.indexOf(name) < 0) deps.push(name); });
    } else visit(parsed.body, parsed.params);
    if (kind === "observation") {
      var probes = options.grantedProbes || worldData.observation && worldData.observation.probes || [];
      reads.forEach(function (name) { if (probes.indexOf(name) < 0) throw new Error("Probe '" + name + "' is not granted."); });
      if (world !== "robot") throw new Error("This observation preview uses the robot world.");
    }
    function infer(node, vars) {
      if (node.node === "Lit") return "int";
      if (node.node === "Var") {
        if (Object.prototype.hasOwnProperty.call(vars, node.name)) return vars[node.name];
        var named = lookup[node.name];
        if (named && named.kind === "observation") return named.spec.sort || "bool";
        if (named && named.kind === "object") return named.spec.sort || "int";
        throw new Error("Cannot use '" + node.name + "' as a value.");
      }
      if (node.node === "Not") { if (infer(node.operand, vars) !== "bool") throw new Error("not expects Bool."); return "bool"; }
      if (node.node === "Test") { if (infer(node.expr, vars) !== "bool") throw new Error("A test must return Bool."); return "bool"; }
      if (node.node === "And" || node.node === "Or") {
        if (infer(node.left, vars) !== "bool" || infer(node.right, vars) !== "bool") throw new Error(node.node + " expects Bool inputs.");
        return "bool";
      }
      if (node.node === "Let") { var local = Object.assign({}, vars); local[node.name] = infer(node.value, vars); return infer(node.body, local); }
      if (node.node === "Case") {
        var choice = infer(node.default, vars);
        node.arms.forEach(function (arm) {
          if (infer(arm[0], vars) !== "bool") throw new Error("A condition must return Bool.");
          if (infer(arm[1], vars) !== choice) throw new Error("Branch sorts must agree.");
        });
        return choice;
      }
      if (node.node === "Call") {
        if (node.fn === slot) { if (infer(node.args[0], vars) !== "int") throw new Error("Slot expects Int."); return "int"; }
        if (node.fn === parsed.name) {
          node.args.forEach(function (arg) { if (infer(arg, vars) !== "int") throw new Error("Recursive input must be Int."); });
          return kind === "law" ? "bool" : "int";
        }
        if (node.fn === "eq" || node.fn === "neq") {
          if (infer(node.args[0], vars) !== infer(node.args[1], vars)) throw new Error("Comparison sorts must agree.");
          return "bool";
        }
        var target = lookup[node.fn], inputs = target.spec.inputs || target.spec.params || [], offset = target.kind === "combinator" ? (target.spec.op_params || []).length : 0;
        node.args.forEach(function (arg, index) {
          if (index < offset) return;
          var input = inputs[index - offset], expected = typeof input === "string" ? "int" : input.sort || "int";
          if (infer(arg, vars) !== expected) throw new Error("'" + node.fn + "' input " + (index + 1) + " expects " + expected + ".");
        });
        return target.spec.output && target.spec.output.sort || target.spec.sort || "int";
      }
      throw new Error("Unsupported expression node.");
    }
    var variableSorts = {};
    parsed.params.forEach(function (param) { variableSorts[param] = "int"; });
    if (parsed.refine) {
      Object.keys(parsed.refine.fields).forEach(function (field) { variableSorts[field] = parsed.refine.fields[field]; });
      if (infer(parsed.refine.valid, variableSorts) !== "bool") throw new Error("Refine predicate must return Bool.");
    } else {
      var resultSort = infer(parsed.body, variableSorts);
      var required = kind === "observation" || kind === "law" ? "bool" : "int";
      if (resultSort !== required) throw new Error("Output sort " + resultSort + " cannot be used as " + required + ".");
    }
    var layer = Math.max(0, ...deps.map(function (name) { return lookup[name] ? lookup[name].layer : 0; })) + 1;
    if (parsed.declaredLayer !== layer) throw new Error("Declared L" + parsed.declaredLayer + " disagrees with computed L" + layer + ".");
    return { depends_on: deps, reads: reads, layer: layer };
  }

  function evaluate(parsed, kind, world, args, library, options) {
    options = options || {}; library = library || []; var mock = A2.mock || { defs: [] }, defs = (mock.defs || []).filter(function (item) { return item.world === world; }).concat(library.filter(function (item) { return item.world === world; }));
    var byName = {}; defs.forEach(function (item) { byName[item.name] = item; });
    var nextId = 0, fuel = options.fuel === undefined ? 250 : options.fuel, used = 0, depth = 0;
    function charge(cost) {
      if (!Number.isSafeInteger(cost) || cost < 0) throw { bottom: "invalid" };
      if (used + cost > fuel) throw { unknown: "fuel" };
      used += cost;
    }
    function exact(value) {
      if (typeof value === "number" && !Number.isSafeInteger(value)) throw { bottom: "unsafe_integer" };
      if (value && typeof value === "object") {
        if (value.t === "int") { if (!Number.isSafeInteger(value.v)) throw { bottom: "unsafe_integer" }; }
        else if (!Array.isArray(value.f)) throw { bottom: "unsafe_integer" };
        else value.f.forEach(function (field) { if (!field || field.t !== "int") throw { bottom: "unsafe_integer" }; exact(field); });
      }
      return value;
    }
    function leaf(name, values, result, kindName) { return { id: "d" + nextId++, path: [], def: name, kind: kindName || "operation", layer: 0, given: true, args: values, result: result, children: [] }; }
    function run(node, env, children) {
      if (node.node === "Lit") return node.value.v;
      if (node.node === "Var") {
        if (Object.prototype.hasOwnProperty.call(env, node.name)) return env[node.name];
        var named = byName[node.name];
        if (named && named.kind === "object") {
          if (named.origin === "given") { var result = named.name === "Zero" ? 0 : named.name; children.push(leaf(named.name, [], result, "object")); return result; }
          return call(named.name, [], children);
        }
        if (named && named.kind === "observation") return call(named.name, [], children);
        if (named && named.kind === "operation") return node.name;
        throw { bottom: "invalid" };
      }
      if (node.node === "Let") { var local = Object.assign({}, env); local[node.name] = run(node.value, env, children); return run(node.body, local, children); }
      if (node.node === "Test") return !!run(node.expr, env, children);
      if (node.node === "Not") return !run(node.operand, env, children);
      if (node.node === "And") { var first = run(node.left, env, children); return first && !!run(node.right, env, children); }
      if (node.node === "Or") { var left = run(node.left, env, children); return left || !!run(node.right, env, children); }
      if (node.node === "Case") { for (var arm of node.arms) if (run(arm[0], env, children)) return run(arm[1], env, children); return run(node.default, env, children); }
      if (node.node === "Call") return call(Object.prototype.hasOwnProperty.call(env, node.fn) ? env[node.fn] : node.fn, node.args.map(function (arg) { return run(arg, env, children); }), children);
      throw { bottom: "invalid" };
    }
    function call(name, values, parent) {
      values.forEach(exact);
      var def = name === parsed.name ? { name: parsed.name, kind: kind, layer: options.layer || 1, spec: kind === "combinator" ? { op_params: [{ name: parsed.params[0] }], params: parsed.params.slice(1) } : { params: parsed.params }, body: parsed.body, origin: "invented" } : byName[name];
      if (!def && (name === "neq" || name === "eq")) { charge(1); var comparison = name === "neq" ? values[0] !== values[1] : values[0] === values[1]; parent.push(leaf(name, values, comparison)); return comparison; }
      if (!def) throw { bottom: "invalid" };
      if (def.origin === "given") {
        if (def.kind !== "object") charge(def.cost === undefined ? 1 : def.cost);
        var result;
        switch (name) {
          case "add": result = values[0] + values[1]; break;
          case "succ": result = values[0] + 1; break;
          case "dec": result = values[0] - 1; break;
          case "neg": result = -values[0]; break;
          case "is_zero": result = values[0] === 0; break;
          case "lt": result = values[0] < values[1]; break;
          case "eq": result = values[0] === values[1]; break;
          case "neq": result = values[0] !== values[1]; break;
          case "mod":
            if (!values[1]) throw { bottom: "div_zero" };
            var modulus = BigInt(values[1]);
            result = Number(((BigInt(values[0]) % modulus) + modulus) % modulus);
            break;
          case "front_wall": result = !!(options.probes || {}).front_wall; break;
          case "front_water": result = !!(options.probes || {}).front_water; break;
          default: throw { bottom: "invalid" };
        }
        exact(result); parent.push(leaf(name, values, result, def.kind)); return result;
      }
      if (depth >= 512) throw { unknown: "depth" };
      depth++;
      try {
        var kids = [], names = def.spec && def.spec.params || parsed.params;
        if (def.kind === "combinator") names = (def.spec.op_params || []).map(function (p) { return p.name; }).concat((def.spec.params || []).map(function (p) { return typeof p === "string" ? p : p.name; }));
        var local = {}; names.forEach(function (param, index) { local[typeof param === "string" ? param : param.name] = values[index]; });
        var result;
        var refine = def.name === parsed.name ? parsed.refine : def.refine;
        if (refine) {
          var fields = refine.fields, keys = Object.keys(fields); keys.forEach(function (key, index) { local[key] = values[index]; });
          if (keys.some(function (key) { return !Number.isSafeInteger(local[key]); })) throw { bottom: "unsafe_integer" };
          if (!run(refine.valid, local, kids)) throw { bottom: "invalid" };
          if (refine.canon === "reduce" && local.den === 0) throw { bottom: "div_zero" };
          if (refine.canon === "reduce") {
            var numerator = BigInt(local.num), denominator = BigInt(local.den), gcd = function (a, b) { return b ? gcd(b, a % b) : a < 0n ? -a : a; }; var divisor = gcd(numerator, denominator);
            if (!divisor) throw { bottom: "div_zero" };
            var sign = denominator < 0n ? -1n : 1n;
            result = { t: def.name, tag: def.name, f: [{ t: "int", v: Number(sign * numerator / divisor) }, { t: "int", v: Number(sign * denominator / divisor) }] };
          } else result = { t: def.name, tag: def.name, f: [{ t: "int", v: Number(((BigInt(values[0]) % 12n) + 12n) % 12n) }] };
          exact(result);
          var canonical = {}; keys.forEach(function (key, index) { canonical[key] = result.f[index].v; });
          if (!run(refine.valid, canonical, kids)) throw { bottom: "invalid" };
        } else result = run(def.body, local, kids);
        exact(result);
        var scope = def.evidence && def.evidence.scope;
        var outsideCheckedScope = !!scope && (!scope.predicate || scope.predicate.type !== "cases" || !scope.predicate.cases.some(function (entry) { return JSON.stringify(entry) === JSON.stringify(def.kind === "observation" ? [!!(options.probes || {}).front_wall, !!(options.probes || {}).front_water] : values); }));
        parent.push({ id: "d" + nextId++, path: [], def: def.name, kind: def.kind, layer: def.layer, given: false, args: values, result: result, children: kids, emptyBody: kids.length === 0, outsideCheckedScope: outsideCheckedScope });
        return result;
      } finally { depth--; }
    }
    var top = [];
    try {
      var result = call(parsed.name, args || [], top);
      var tree = top[0];
      function paths(node, path) { node.path = path; (node.children || []).forEach(function (child, index) { paths(child, path.concat(index)); }); }
      if (tree) {
        paths(tree, []);
        function markOutsidePath(node) {
          var outside = !!node.outsideCheckedScope;
          (node.children || []).forEach(function (child) { outside = markOutsidePath(child) || outside; });
          node.containsOutsideCheckedScope = outside;
          return outside;
        }
        markOutsidePath(tree);
      }
      return { outcome: { ok: typeof result === "boolean" ? { t: "bool", tag: String(result), f: [] } : typeof result === "number" ? { t: "int", v: result } : result }, result: result, tree: tree, steps: used };
    } catch (error) { return { outcome: error && (error.bottom || error.unknown) ? error : { bottom: "invalid" }, tree: null, steps: used }; }
  }

  function verify(parsed, kind, world, library, options) {
    options = options || {}; var method = options.method || "exhaustive";
    if (["exhaustive", "bounded", "sampled"].indexOf(method) < 0) return { ok: false, error: "Unknown verification method '" + method + "'." };
    if (kind === "combinator" && method === "exhaustive") method = "bounded";
    var cases = [], seed = method === "sampled" && options.seed !== undefined ? Number(options.seed) : 7;
    if (method === "sampled" && (!Number.isInteger(seed) || seed < 1 || seed > 4294967295)) return { ok: false, error: "Seed must be an integer in 1..4294967295." };
    if (method === "sampled" && (parsed.refine || !parsed.params.length && kind !== "observation")) return { ok: false, error: "Seeded sampling is unavailable for this object; enumerate its listed cases." };
    function random() { seed = (Math.imul(1664525, seed) + 1013904223) >>> 0; return (seed >>> 16) % 16; }
    if (kind === "operation" && parsed.params.length === 2) {
      if (method === "sampled") for (var sample = 0; sample < 24; sample++) cases.push([random(), random()]);
      else for (var a = 0; a <= 15; a++) for (var b = 0; b <= 15; b++) cases.push([a, b]);
    } else if ((kind === "operation" || kind === "law" || kind === "bridge") && parsed.params.length === 1) {
      for (var input = 0; input < (method === "sampled" ? 12 : 16); input++) cases.push([method === "sampled" ? random() : input]);
    } else if (kind === "combinator") {
      if (method === "sampled") for (var choice = 0; choice < 12; choice++) cases.push([["succ", "dec", "neg"][random() % 3], random()]);
      else ["succ", "dec", "neg"].forEach(function (op) { for (var value = 0; value < 16; value++) cases.push([op, value]); });
    } else if (kind === "observation") cases = method === "sampled" ? Array.from({ length: 12 }, function () { return [!!(random() % 2), !!(random() % 2)]; }) : [[false, false], [false, true], [true, false], [true, true]];
    else if (parsed.refine) cases = parsed.refine.canon === "reduce" ? [[2, 4], [3, 0], [0, 0], [1, 2], [-2, 4], [2, -4], [-2, -4]] : [[14], [2], [26], [12], [0]];
    else if (parsed.params.length === 0) cases = [[]];
    else return { ok: false, error: "Only unary and binary Int signatures are supported by this preview." };
    for (var entry of cases) {
      var probes = kind === "observation" ? { front_wall: entry[0], front_water: entry[1] } : {};
      var args = kind === "observation" || kind === "object" && !parsed.refine ? [] : entry;
      var actual = evaluate(parsed, kind, world, args, library, { probes: probes, fuel: 300, layer: options.layer });
      if (actual.outcome.unknown) return { ok: false, error: "Unknown(fuel) at " + JSON.stringify(entry) + "; not verified." };
      if (actual.outcome.bottom && !(parsed.refine && parsed.refine.canon === "reduce" && entry[1] === 0 && actual.outcome.bottom === "invalid")) return { ok: false, error: "Bottom(" + actual.outcome.bottom + ") at " + JSON.stringify(entry) + "." };
      if (parsed.refine && !actual.outcome.bottom) {
        var canonical = actual.result.f.map(function (field) { return field.v; });
        var repeated = evaluate(parsed, kind, world, canonical, library, { fuel: 300 });
        if (repeated.outcome.bottom || repeated.outcome.unknown || JSON.stringify(repeated.result) !== JSON.stringify(actual.result)) return { ok: false, error: "Canon is not valid and idempotent at " + JSON.stringify(entry) + ".", counterexample: entry };
      }
      if ((options.reference === "mul" || options.reference === "reference mul") && kind === "operation" && parsed.params.length === 2) {
        var expected = entry[0] * entry[1];
        if (actual.result !== expected) return { ok: false, error: "First counterexample: " + parsed.name + "(" + entry.join(", ") + ") = " + actual.result + ", reference mul = " + expected + ".", counterexample: entry };
      }
      if (options.reference && options.reference !== "mul" && options.reference !== "reference mul" && options.reference !== "twice") {
        var referenceDef = (A2.mock.defs || []).concat(library || []).filter(function (def) { return def.name === options.reference && def.world === world; })[0];
        if (referenceDef) {
          var referenceBody = { node: "Call", fn: referenceDef.name, args: parsed.params.map(function (param) { return { node: "Var", name: param }; }) };
          if (referenceDef.kind === "object" || referenceDef.kind === "observation") referenceBody = { node: "Var", name: referenceDef.name };
          var expectedResult = evaluate({ name: "preview_reference", params: parsed.params, body: referenceBody }, kind, world, args, library, { probes: probes, fuel: 300 });
          if (expectedResult.outcome.unknown || JSON.stringify(actual.outcome) !== JSON.stringify(expectedResult.outcome)) return { ok: false, error: "First counterexample: " + JSON.stringify(entry) + "; differs from " + referenceDef.name + ".", counterexample: entry };
        }
      }
      if (kind === "combinator" && options.reference === "twice") {
        var once = entry[0] === "succ" ? entry[1] + 1 : entry[0] === "dec" ? entry[1] - 1 : -entry[1];
        var expectedTwice = entry[0] === "succ" ? once + 1 : entry[0] === "dec" ? once - 1 : -once;
        if (actual.result !== expectedTwice) return { ok: false, error: "First counterexample: " + entry.join(", ") + ".", counterexample: entry };
      }
    }
    if (parsed.refine && parsed.refine.canon === "reduce") {
      var alternate = evaluate(parsed, kind, world, [1, 2], library, { fuel: 300 });
      var equivalent = evaluate(parsed, kind, world, [2, 4], library, { fuel: 300 });
      if (JSON.stringify(alternate.result) !== JSON.stringify(equivalent.result)) return { ok: false, error: "Equivalent fraction representations have different canonical values.", counterexample: [[1, 2], [2, 4]] };
    }
    var full = method !== "sampled" && (parsed.params.length === 0 && !parsed.refine ||
      kind === "observation" || kind === "combinator" || (parsed.params.length === 1 && cases.length === 16) ||
      (parsed.params.length === 2 && cases.length === 256));
    if (method === "exhaustive" && !full) method = "bounded";
    var domain = method === "sampled" ? "seeded cases " + JSON.stringify(cases) : kind === "observation" ? "all four probe pairs" :
      kind === "combinator" ? "f in {succ, dec, neg}; x in 0..15" : parsed.refine ? "listed canonicalization inputs " + JSON.stringify(cases) :
      parsed.params.length === 0 ? "closed term (one case)" : parsed.params.join(", ") + " in 0..15";
    return { ok: true, evidence: { method: method, scope: { domain: domain, size: cases.length, description: "Previewed " + cases.length + " cases", cases: cases, predicate: { type: "cases", cases: cases } }, seed: method === "sampled" ? Number(options.seed === undefined ? 7 : options.seed) : null, checks: options.reference ? ["reference"] : parsed.refine ? ["canonicalization"] : ["evaluation_only"] } };
  }

  function pipeline(text, kind, world, options) {
    options = options || {}; var stations = ["written", "checked", "callable", "verified", "previewed"].map(function (status) { return { status: status, ok: null, detail: "Waiting" }; });
    var record = null, evidence = null, parsed, checked, sample;
    function failure(index, message) { stations[index].ok = false; stations[index].detail = message; if (record) { record.status = "failed"; record.failed = { at: stations[index].status, reason: message }; } return { stations: stations, record: record, evidence: evidence, error: message }; }
    try { parsed = parse(text, kind); stations[0].ok = true; stations[0].detail = "Parsed " + parsed.name + "."; } catch (error) { return failure(0, error.message); }
    var library = options.library || [];
    if (kind === "law" || kind === "bridge") {
      try { checked = check(parsed, kind, world, library, options); } catch (error) { return failure(0, error.message); }
      stations[0].detail += " Computed L" + checked.layer + "; syntax and sorts only: this preview does not verify " + kind + " contracts.";
      return { stations: stations, record: { name: parsed.name, kind: kind, layer: checked.layer, status: "written" }, evidence: null, error: null, parsed: parsed };
    }
    try { checked = check(parsed, kind, world, library, options); stations[1].ok = true; stations[1].detail = "Computed L" + checked.layer + " from " + (checked.depends_on.join(", ") || "a closed term") + "."; } catch (error) { return failure(1, error.message); }
    library = library.filter(function (item) { return item.world !== world || item.name !== parsed.name; });
    var hash = contentHash(text, kind, world, dependencyHashes(checked.depends_on, world, library));
    record = { id: world + "@preview/" + parsed.name + "/" + hash, content_hash: hash, source: text, session: true, world: world, name: parsed.name, kind: kind, origin: "invented", layer: checked.layer, depends_on: checked.depends_on,
      spec: kind === "operation" || kind === "law" || kind === "bridge" ? { params: parsed.params, inputs: parsed.params.map(function () { return { sort: "int" }; }), output: { sort: kind === "law" ? "bool" : "int" }, role: "preview" } : kind === "combinator" ? { op_params: [{ name: parsed.params[0], type: "int -> int" }], params: parsed.params.slice(1).map(function (name) { return { name: name, sort: "int" }; }), unfold: text } : kind === "observation" ? { reads: checked.reads, sort: "bool" } : parsed.refine ? { form: "refine", base: { record: parsed.refine.fields }, valid: (text.match(/\bwhere\s+(.+?)\s+canon\s+/) || [null, "predicate"])[1], canon: parsed.refine.canon, sealed: true, interface: ["make"].concat(Object.keys(parsed.refine.fields)) } : { form: "constant", sort: "int" },
      body: parsed.body, refine: parsed.refine, evidence: null, contract: null, cost: { length: tokenize(text).length - 1, steps: { min: 0, max: 0, mean: 0, over: "preview", example: null }, reuse: 0 }, status: "checked" };
    var args = options.sample || (parsed.refine ? parsed.refine.canon === "reduce" ? [2, 4] : [14] : kind === "operation" || kind === "bridge" || kind === "law" ? parsed.params.length === 2 ? [11, 13] : [13] : kind === "combinator" ? ["succ", 11] : []);
    sample = evaluate(parsed, kind, world, args, library, { fuel: options.fuel, layer: record.layer, probes: options.probes || { front_wall: false, front_water: false } });
    if (sample.outcome.bottom) return failure(2, "Sample returned Bottom(" + sample.outcome.bottom + ").");
    if (sample.outcome.unknown) return failure(2, "Sample returned Unknown(" + sample.outcome.unknown + "). " + (sample.outcome.unknown === "fuel" ? "Increase the fuel or reduce charged calls." : "Reduce recursion depth."));
    record.status = "callable"; record.cost.steps = { min: sample.steps, max: sample.steps, mean: sample.steps, over: "sample", example: { call: parsed.name + "(" + args.join(", ") + ")", steps: sample.steps } };
    stations[2].ok = true; stations[2].detail = "Sample returned Ok(" + JSON.stringify(sample.result) + "); " + sample.steps + " preview steps.";
    if (options.verify === false) return { stations: stations, record: record, evidence: null, error: null, sample: sample, parsed: parsed };
    var proof = verify(parsed, kind, world, library, Object.assign({}, options, { layer: record.layer }));
    if (!proof.ok) return failure(3, proof.error);
    evidence = proof.evidence; record.evidence = evidence;
    if (!options.reference && !parsed.refine) {
      record.status = "evaluated (no reference check)";
      stations[3].status = record.status;
    } else record.status = "verified";
    record.contract = { guarantees: options.reference ? "Matches " + options.reference + " on listed cases" : parsed.refine ? "Canonicalizes listed representations" : "Values only on listed cases; no equivalence claim", may_change: [], keeps: [] };
    stations[3].ok = true; stations[3].detail = "Previewed " + evidence.scope.size + " cases: " + evidence.scope.domain + ".";
    if (["exhaustive", "bounded"].indexOf(evidence.method) < 0 || !options.reference && !parsed.refine) { stations[4].detail = !options.reference && !parsed.refine ? "Evaluated (no reference check); no equivalence claim." : "Case check only: no reference or canonicalization check on a complete declared scope."; return { stations: stations, record: record, evidence: evidence, error: null, sample: sample, parsed: parsed }; }
    record.status = "previewed"; stations[4].ok = true; stations[4].detail = "Browser comparison against a reference or canonicalization on " + evidence.scope.domain + ".";
    return { stations: stations, record: record, evidence: evidence, error: null, sample: sample, parsed: parsed };
  }

  function evidenceKey(text, kind, settings) {
    return JSON.stringify([text, kind, settings.method, settings.reference, String(settings.seed)]);
  }

  function canAdvance(current, frame) {
    return !!current && frame < 5 && (frame === 0 || current.stations[frame - 1].ok === true) && current.stations[frame].ok !== null;
  }

  function mount(host, mock) {
    mock = mock || { defs: [] };
    var kind = "operation", library = [], detachedEvidence = [], towerWorld = false, current = null, frame = 0, playing = false, timer = null, tree = null, boundaryViewer = null, boundaryObserver = null;
    var section = el("section", { class: "a2-define", tabindex: "0" });
    var tabs = el("div", { class: "a2-define-tabs", role: "tablist", "aria-label": "Definition kind" });
    var columns = el("div", { class: "a2-define-columns" }), editor = el("div", { class: "a2-panel a2-define-editor" });
    var resultPane = el("div", { class: "a2-panel a2-define-result" });
    var header = el("div", { class: "a2-define-section-head" }, [el("span", { class: "a2-define-number", text: "01" }), el("strong", { text: "Write the definition" })]);
    var syntax = el("p", { class: "a2-define-hint" });
    var text = el("textarea", { class: "a2-define-text", spellcheck: "false", "aria-label": "Definition source", rows: "5" });
    var presets = el("div", { class: "a2-define-presets" });
    var method = el("select", { class: "a2-define-select", "aria-label": "Verification method" }, [el("option", { value: "exhaustive", text: "Enumerate finite scope" }), el("option", { value: "sampled", text: "Seeded sample" })]);
    var reference = el("select", { class: "a2-define-select", "aria-label": "Claims to equal" });
    var seed = el("input", { class: "a2-define-input", type: "number", min: "1", max: "4294967295", step: "1", value: "7", "aria-label": "Sample seed" });
    var seedField = el("label", {}, ["Sample seed", seed]);
    var verifyFields = el("div", { class: "a2-define-settings" }, [el("label", {}, ["Browser case-check method", method]), el("label", {}, ["Claims to equal", reference]), seedField]);
    var run = el("button", { type: "button", class: "a2-btn a2-define-run", text: "Run preview" });
    var controls = el("div", { class: "a2-define-controls" });
    var back = el("button", { type: "button", class: "a2-btn", "aria-label": "Step back", text: "Back" });
    var play = el("button", { type: "button", class: "a2-btn", "aria-label": "Play or pause pipeline", text: "Play" });
    var next = el("button", { type: "button", class: "a2-btn", "aria-label": "Next lifecycle stage", text: "Next" });
    var counter = el("span", { class: "a2-define-counter", "aria-live": "polite" });
    var store = el("button", { type: "button", class: "a2-btn a2-define-store", text: "Store in session", "aria-label": "Store browser preview in session" });
    controls.append(back, play, next, counter, store);
    var cardHolder = el("div", { class: "a2-define-card" }), status = el("div", { class: "a2-define-status", "aria-live": "polite" });
    var stations = el("div", { class: "a2-define-stations" });
    var towerButton = el("button", { type: "button", class: "a2-btn", text: "Build four-kind preview" });
    var towerStatus = el("p", { class: "a2-define-hint", role: "status" });
    editor.append(header, syntax, presets, towerButton, towerStatus,
      el("p", { class: "a2-define-hint", text: "Type the ASCII storage form; the preview shows notation v3." }), text, verifyFields, run, controls);
    resultPane.append(el("div", { class: "a2-define-section-head" }, [el("span", { class: "a2-define-number", text: "02" }), el("strong", { text: "Follow the lifecycle" })]), cardHolder, stations, status);
    columns.append(editor, resultPane);
    var tabPanel = el("div", { id: "a2-define-tabpanel", role: "tabpanel", tabindex: "0" }, columns);
    var shelves = el("div", { class: "a2-panel a2-define-library" });
    var shelfBody = el("div", { class: "a2-define-shelves" });
    shelves.append(el("div", { class: "a2-define-section-head" }, [el("span", { class: "a2-define-number", text: "03" }), el("strong", { text: "Your session library" })]), el("p", { class: "a2-define-hint", text: "Use the current preview now, or store it for later rules. Browser checks apply only to the listed cases." }), shelfBody);
    var usage = el("div", { class: "a2-panel a2-define-use" });
    var expression = el("input", { type: "text", class: "a2-define-input", "aria-label": "Use expression", value: "multiply_preview(13, 17)" });
    var useButton = el("button", { type: "button", class: "a2-btn a2-define-run", text: "Use it" });
    var trace = el("div", { class: "a2-define-boundary" });
    var useStatus = el("div", { class: "a2-define-status", "aria-live": "polite" });
    usage.append(el("div", { class: "a2-define-section-head" }, [el("span", { class: "a2-define-number", text: "04" }), el("strong", { text: "Use it. Change the boundary." })]), el("p", { class: "a2-define-hint", text: "The display cut does not rerun this browser preview. Results outside listed evidence cases are not certified." }), el("div", { class: "a2-define-use-input" }, [expression, useButton]), trace, useStatus);
    section.append(tabs, tabPanel, shelves, usage); host.appendChild(section);

    function worldId() { return towerWorld || kind === "observation" ? "robot" : "integer"; }
    function notation(parsed, source, selectedKind, world, extra) {
      if (!root.N3Convert || !root.N3) return { fallback: "No display form for this construct yet", machine: source };
      return root.N3Convert.preview(parsed, selectedKind, world, mock.defs, extra || library, source);
    }
    function formula(display, source) {
      if (display && root.N3Convert) return root.N3Convert.render(display);
      return el("span", {}, ["No display form for this construct yet ", el("code", { text: source || "" })]);
    }
    function definitionPreview(parsed, source, selectedKind, world, extra) {
      var result = notation(parsed, source, selectedKind, world, extra);
      if (result.fallback) return formula(null, source);
      return el("span", {}, [result.signature ? el("code", { class: "a2-expr" }, root.N3Convert.render(result.signature)) : null,
        el("code", { class: "a2-expr" }, root.N3Convert.render(result.formula))]);
    }
    function activeAtoms(world) {
      return current && current.record && current.record.world === world && current.parsed &&
        !library.some(function (entry) { return entry.world === world && entry.name === current.record.name; }) ? library.concat([current.record]) : library;
    }
    function visibleValue(value, world) {
      var item = root.N3Convert && root.N3Convert.value(value, world, mock.defs, activeAtoms(world));
      return item ? root.N3Convert.render(item.display) : formula(null, JSON.stringify(value));
    }
    function statusDetail(detail, world) {
      var match = /\b(Ok|Bottom|Unknown)\(([^)]*)\)/.exec(detail);
      if (match) {
        var value;
        try { value = match[1] === "Ok" ? { ok: JSON.parse(match[2]) } : match[1] === "Bottom" ? { bottom: match[2] } : { unknown: match[2] }; }
        catch (error) { return el("span", {}, [detail.slice(0, match.index), formula(null, match[0]), detail.slice(match.index + match[0].length)]); }
        return el("span", {}, [detail.slice(0, match.index), visibleValue(value, world), detail.slice(match.index + match[0].length)]);
      }
      var read = /\?[A-Za-z_][A-Za-z_0-9]*\{[^{}]*\}/.exec(detail);
      return read ? el("span", {}, [detail.slice(0, read.index), visibleCall(read[0], world), detail.slice(read.index + read[0].length)]) : detail;
    }
    function visibleCall(source, world, available) {
      try {
        var parsed = parse("preview_use = " + source + " L1", "operation");
        var converted = notation(parsed, source, "operation", world, available || library);
        if (converted.formula) {
          var head = converted.formula.split(" = { ")[1].slice(0, -2);
          return root.N3Convert.render(head);
        }
      } catch (error) { return formula(null, source); }
      return formula(null, source);
    }
    function traceCall(name, values, world) {
      var active = activeAtoms(world), marks = root.N3Convert.worldLegend(world, mock.defs, active);
      var atom = marks.find(function (entry) { return entry.name === name.replace(/^[@?#~]/, ""); });
      if (!atom && (name === "eq" || name === "neq")) atom = { display: name === "eq" ? "(==)" : "(!=)", kind: "operation" };
      if (!atom) return formula(null, name + "(" + values.map(A2.formatValue).join(", ") + ")");
      if (atom.kind === "combinator") {
        var definition = (mock.defs || []).concat(active).find(function (entry) { return entry.world === world && entry.name === name; });
        var count = definition && definition.spec && (definition.spec.op_params || []).length || 0;
        var operations = values.slice(0, count).map(function (value) { var entry = marks.find(function (item) { return item.name === value; }); return entry && entry.display; });
        var inputs = values.slice(count).map(function (value) { var display = root.N3Convert.value(value, world, mock.defs, active); return display && display.display; });
        if (operations.some(function (value) { return !value; }) || inputs.some(function (value) { return !value; }))
          return formula(null, name + "(" + values.map(A2.formatValue).join(", ") + ")");
        return root.N3Convert.render(atom.display + "[" + operations.join(", ") + "]" +
          (inputs.length === 1 && !/^[\-\[]/.test(inputs[0]) ? " " + inputs[0] : "(" + inputs.join(", ") + ")"));
      }
      var args = values.map(function (value) { var display = root.N3Convert.value(value, world, mock.defs, active); return display && display.display; });
      if (args.some(function (value) { return !value; })) return formula(null, name + "(" + values.map(A2.formatValue).join(", ") + ")");
      var mark = atom.display, text = mark + "(" + args.join(", ") + ")";
      if (atom.kind === "observation") text = mark + "⟨" + args.join(", ") + "⟩";
      else if (args.length === 2 && atom.kind === "operation") {
        var sign = /^\(.+\)$/.test(mark);
        text = (sign || args[0][0] !== "-" ? args[0] : "(" + args[0] + ")") + " " + (sign ? mark.slice(1, -1) : mark) + " " +
          (sign || args[1][0] !== "-" ? args[1] : "(" + args[1] + ")");
      } else if (args.length === 1 && atom.kind === "operation") text = mark === "@" ? args[0] + " @" : args[0][0] === "-" ? mark + "(" + args[0] + ")" : mark + " " + args[0];
      return root.N3Convert.render(text);
    }
    function displayBoundary(node, world, rootNode) {
      var byId = {}, pending = [rootNode];
      while (pending.length) { var item = pending.pop(); byId[item.id] = item; pending.push.apply(pending, item.children || []); }
      function refresh() {
        var marks = root.N3Convert.worldLegend(world, mock.defs, activeAtoms(world));
        node.querySelectorAll(".a2-chip-name").forEach(function (name) {
          if (name.querySelector(".n3, code")) return;
          var atom = marks.find(function (entry) { return entry.name === name.textContent.replace(/^[@?#~]/, ""); });
          name.replaceChildren(atom ? root.N3Convert.render(atom.display) : formula(null, name.textContent));
        });
        node.querySelectorAll(".a2-boundary-row[data-flip]").forEach(function (row) {
          var args = row.querySelector(".a2-boundary-args");
          if (!args || args.querySelector(".n3, code")) return;
          var item = byId[row.getAttribute("data-flip")];
          if (!item) return;
          args.replaceChildren(traceCall(item.def, item.args || [], world));
          var value = row.querySelector(".a2-boundary-expression");
          if (value && value.lastElementChild && value.lastElementChild !== args &&
              !value.lastElementChild.matches(".n3, code") && !value.lastElementChild.querySelector(".n3, code"))
            value.lastElementChild.replaceWith(visibleValue(item.result, world));
        });
        var pinned = node.querySelector(".a2-boundary-pinned .a2-v");
        if (pinned && !pinned.querySelector(".n3, code")) pinned.replaceChildren(visibleValue(rootNode.result, world));
      }
      refresh();
      if (root.MutationObserver) { boundaryObserver = new root.MutationObserver(refresh); boundaryObserver.observe(node, { childList: true, subtree: true }); }
    }

    function button(label, action) { return el("button", { type: "button", class: "a2-btn", onclick: action, text: label }); }
    function stop() { playing = false; clearTimeout(timer); play.textContent = "Play"; }
    function invalidate() { if (!current) return; stop(); current = null; frame = 0; store.disabled = true; draw(); status.textContent = "Source or settings changed. Run the preview again before storing."; }
    function updateSeed() { seedField.hidden = method.value !== "sampled"; seed.disabled = seedField.hidden; invalidate(); }
    text.addEventListener("input", invalidate);
    method.addEventListener("change", updateSeed);
    reference.addEventListener("change", invalidate);
    seed.addEventListener("input", invalidate);
    function options() { return { library: library, method: method.value, seed: Number(seed.value), reference: reference.value }; }
    function refreshReferences() {
      var selected = reference.value;
      reference.replaceChildren(el("option", { value: "", text: "No reference (evaluation only)" }));
      if (kind === "operation") reference.appendChild(el("option", { value: "mul", text: "Reference mul (repeated addition)" }));
      if (kind === "combinator") reference.appendChild(el("option", { value: "twice", text: "Reference twice (f(f(x)))" }));
      (mock.defs || []).concat(library).filter(function (def) { return def.kind === kind && def.world === (kind === "observation" ? "robot" : "integer") && ["mul", "twice"].indexOf(def.name) < 0; }).forEach(function (def) {
        reference.appendChild(el("option", { value: def.name, text: def.name + (def.origin === "given" ? " (world atom)" : " (session definition)") }));
      });
      if (Array.prototype.some.call(reference.options, function (option) { return option.value === selected; })) reference.value = selected;
    }
    function refreshLibrary() {
      shelfBody.replaceChildren(); var world = towerWorld || kind === "observation" ? "robot" : "integer";
      var marks = root.N3Convert.worldLegend(world, mock.defs, library);
      var available = (mock.defs || []).filter(function (def) { return def.world === world && def.layer === 0; }).concat(library.filter(function (def) { return def.world === world; }));
      var grouped = {};
      available.forEach(function (def) { (grouped[def.layer] || (grouped[def.layer] = [])).push(def); });
      Object.keys(grouped).map(Number).sort(function (a, b) { return b - a; }).forEach(function (layer) {
        var row = el("div", { class: "a2-define-shelf" }, [el("span", { class: "a2-define-layer", text: layer === 0 ? "Given" : "L" + layer })]);
        grouped[layer].forEach(function (def) {
          var mark = marks.find(function (item) { return item.name === def.name.replace(/^[@?#~]/, "") && item.kind === def.kind; });
          row.appendChild(mark ? root.N3Convert.render(mark.display) : formula(null, def.name));
          if (def.evidence && def.evidence.method === "sampled") row.appendChild(A2.badge("sampled", { scope: def.evidence.scope.domain }));
        }); shelfBody.appendChild(row);
      });
      detachedEvidence.filter(function (item) { return item.world === world; }).forEach(function (item) {
        var mark = marks.find(function (entry) { return entry.name === item.name.replace(/^[@?#~]/, ""); });
        shelfBody.appendChild(el("div", { class: "a2-define-shelf" }, [el("span", { class: "a2-define-layer", text: "Detached" }), mark ? root.N3Convert.render(mark.display) : formula(null, item.name),
          el("span", { text: " @" + item.content_hash + ": old " + item.evidence.method + " evidence detached (" + item.evidence.scope.domain + ")." })]));
      });
    }
    function draw() {
      var writeOnly = kind === "law" || kind === "bridge";
      counter.textContent = "Step " + frame + " / " + (writeOnly ? 1 : 5);
      back.disabled = !current || frame <= 0;
      next.disabled = !canAdvance(current, frame);
      play.disabled = !canAdvance(current, frame);
      store.disabled = !current || frame < (current.record && ["verified", "evaluated (no reference check)"].includes(current.record.status) ? 4 : 5) || !current.record || !["previewed", "verified", "evaluated (no reference check)"].includes(current.record.status);
      stations.replaceChildren();
      if (!current) { cardHolder.replaceChildren(el("div", { class: "a2-define-empty" }, [A2.icon(kind), el("strong", { text: "Your definition will appear here" }), el("span", { text: "Run the browser stages: write, check, call and preview finite cases." })])); status.textContent = "Waiting for a definition."; return; }
      var visible = current.stations.slice(0, frame), last = visible[visible.length - 1], record = current.record;
      if (record && frame >= 2) {
        var failed = visible.find(function (entry) { return entry.ok === false; });
        cardHolder.replaceChildren(definitionPreview(current.parsed, text.value, kind, worldId()), A2.badge("design"), el("small", { text: "Browser preview: " + (failed ? "failed at " + failed.status : last && last.ok ? last.status === "verified" ? "cases previewed" : last.status : "written") + "." }));
      } else cardHolder.replaceChildren(el("div", { class: "a2-define-empty" }, [A2.icon(kind), el("strong", { text: frame ? "Parsing the source" : "Ready when you are" }), el("span", { text: "Each station records what the check learned." })]));
      current.stations.slice(0, writeOnly ? 1 : 5).forEach(function (item, index) {
        var name = item.status, shown = index < frame, cls = shown ? item.ok === false ? " a2-define-failed" : item.ok ? " a2-define-passed" : " a2-define-locked" : index === 4 && record && record.status === "verified" && frame >= 4 ? " a2-define-locked" : "";
        stations.appendChild(el("div", { class: "a2-define-station" + cls, style: { "--a2-define-delay": index * 45 + "ms" } }, [el("span", { class: "a2-define-station-index", text: shown ? item.ok === false ? "!" : item.ok ? "yes" : "no" : String(index + 1) }), el("div", {}, [el("strong", { text: name === "verified" ? "cases previewed" : name === "previewed" ? record && record.status === "evaluated (no reference check)" ? "reference check not run" : "reference previewed" : name }), el("small", {}, shown ? statusDetail(item.detail, worldId()) : index === 4 && record && record.evidence && record.evidence.method === "sampled" ? "Sampled cases only" : "Waiting for the previous station")]) ]));
      });
      status.replaceChildren(last && (last.ok === false || last.ok === null) ? statusDetail(last.detail, worldId()) : record && record.status === "written" ? "Syntax, sorts and layer checked. No contract check or evidence." : record && frame === 5 && record.status === "previewed" ? "Ready to store this case-scoped preview result." : record && frame >= 4 && record.status === "evaluated (no reference check)" ? "Evaluated (no reference check). Ready to store without an equivalence claim." : record && frame >= 4 && record.status === "verified" ? "Callable in this preview. Case evidence stays scoped." : "Moving through the preview stages.");
      status.classList.toggle("a2-define-error", !!(last && last.ok === false));
    }
    function advance() { if (!canAdvance(current, frame)) { stop(); return; } frame++; draw(); if (playing && canAdvance(current, frame)) timer = setTimeout(advance, 700); else if (playing) stop(); }
    function submit() {
      stop(); current = pipeline(text.value, kind, towerWorld || kind === "observation" ? "robot" : "integer", options()); frame = 1;
      current.inputKey = evidenceKey(text.value, kind, options());
      if (current.parsed && kind === "operation") expression.value = current.parsed.name + (current.parsed.params.length === 2 ? "(13, 17)" : "(13)");
      draw();
      if (canAdvance(current, frame)) {
        if (root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          while (canAdvance(current, frame)) frame++;
          draw();
        } else { playing = true; play.textContent = "Pause"; timer = setTimeout(advance, 700); }
      }
    }
    towerButton.addEventListener("click", function () {
      var stages = [
        ["object", "obj Beacon = 83 L1"],
        ["operation", "op signal(a) = if eq(a, Beacon) then 1 else 0 L2"],
        ["combinator", "comb @twice_signal[f](x) = f(f(signal(x))) L3"],
        ["observation", "obs ?clear_signal = not ?front_wall{} and not ?front_water{} L1"]
      ];
      stop(); library = library.filter(function (entry) { return entry.world !== "robot" || !["Beacon", "signal", "@twice_signal", "?clear_signal"].includes(entry.name); });
      towerWorld = true;
      var results = [];
      for (var stage of stages) {
        var result = pipeline(stage[1], stage[0], "robot", { library: library, method: "exhaustive", seed: 7 });
        if (result.error || !result.record || !["verified", "previewed", "evaluated (no reference check)"].includes(result.record.status)) {
          towerStatus.textContent = "Tower stopped at " + stage[0] + ": " + (result.error || "no case check") + ".";
          return;
        }
        library.push(result.record);
        results.push({ name: result.record.name, size: result.evidence.scope.size });
      }
      selectKind("observation"); towerWorld = true;
      text.value = stages[3][1]; method.value = "exhaustive"; reference.value = "";
      Array.prototype.forEach.call(tabs.children, function (tab) { var selected = tab.getAttribute("data-kind") === kind; tab.setAttribute("aria-selected", String(selected)); tab.tabIndex = selected ? 0 : -1; });
      resultPane.setAttribute("aria-labelledby", "a2-define-tab-observation");
      current = pipeline(text.value, kind, "robot", { library: library.filter(function (entry) { return entry.name !== "?clear_signal"; }), method: "exhaustive", seed: 7 });
      current.inputKey = evidenceKey(text.value, kind, options()); frame = 4;
      expression.value = "?clear_signal{}";
      refreshLibrary(); refreshReferences(); draw(); use();
      var towerMarks = root.N3Convert.worldLegend("robot", mock.defs, library);
      towerStatus.replaceChildren("Browser case checks: ");
      results.forEach(function (result, index) {
        var mark = towerMarks.find(function (entry) { return entry.name === result.name.replace(/^[@?#~]/, ""); });
        if (index) towerStatus.appendChild(document.createTextNode("; "));
        towerStatus.appendChild(mark ? root.N3Convert.render(mark.display) : formula(null, result.name));
        towerStatus.appendChild(document.createTextNode(" (previewed " + result.size + " cases)"));
      });
      towerStatus.appendChild(document.createTextNode(". The object, operation and combinator form one branch; the observation reads granted probes only."));
    });
    store.addEventListener("click", function () {
      if (!current || !current.record || store.disabled) return;
      if (current.inputKey !== evidenceKey(text.value, kind, options())) { invalidate(); return; }
      var source = cardHolder.querySelector(".a2-card-identity"), from = source && source.getBoundingClientRect();
      var stored = storeSession(library, current.record, detachedEvidence);
      library = stored.library; refreshLibrary(); refreshReferences();
      var destination = Array.prototype.find.call(shelfBody.querySelectorAll(".a2-chip"), function (chip) { return chip.getAttribute("data-def") === current.record.name; });
      if (from && destination) {
        var shelf = destination.parentElement;
        var arrivalKind = "a2-k-" + current.record.kind;
        shelf.classList.add("a2-define-arrived", arrivalKind);
        A2.travel(destination, from, destination.getBoundingClientRect(), 420).then(function () { shelf.classList.remove("a2-define-arrived", arrivalKind); });
      }
      expression.value = current.record.name + (current.parsed && current.parsed.refine ? current.parsed.refine.canon === "reduce" ? "(2, 4)" : "(14)" : current.record.kind === "operation" ? current.parsed.params.length === 2 ? "(13, 17)" : "(13)" : current.record.kind === "combinator" ? "[succ](1)" : current.record.kind === "observation" ? "{}" : "");
      var evidence = current.record.evidence;
      status.textContent = (stored.replaced ? "Replaced session definition. Old evidence detached. " : "") +
        (current.record.status === "previewed" ? "Stored for this session with a browser-only, case-scoped comparison." : current.record.status === "evaluated (no reference check)" ? "Stored as evaluated (no reference check); no equivalence claim." : "Stored as callable preview for this session.") +
        (evidence ? " Browser check: " + evidence.method + "; scope: " + evidence.scope.domain + "." : " No case check recorded.");
      store.disabled = true;
    });
    function selectKind(selected) {
      stop(); if (boundaryObserver) boundaryObserver.disconnect(); boundaryObserver = null; kind = selected; towerWorld = false; towerStatus.textContent = ""; current = null; frame = 0; text.value = featured[kind] || examples[kind].good; syntax.textContent = help[kind];
      method.firstChild.textContent = kind === "combinator" ? "Bounded operation family" : "Enumerate finite scope";
      var writeOnly = kind === "law" || kind === "bridge";
      header.querySelector("strong").textContent = writeOnly ? "Check syntax, sorts and layers for " + kind : "Preview " + kind + " calls and finite cases";
      method.querySelector('[value="sampled"]').disabled = kind === "object";
      if (kind === "object" && method.value === "sampled") method.value = "exhaustive";
      updateSeed();
      verifyFields.hidden = writeOnly;
      run.textContent = writeOnly ? "Parse definition" : "Run preview";
      syntax.textContent = help[kind] + (writeOnly ? "; browser syntax, sorts and layer only (contract not checked here). Core: " + (kind === "law" ? "opulse.atoms.laws.verify_law and replay_rewrite" : "opulse.atoms.bridges.verify_bridge") : "");
      refreshReferences();
      presets.replaceChildren();
      presetsFor(kind).forEach(function (choice) { presets.appendChild(button(choice.label, function () { text.value = choice.source; method.value = choice.sampled ? "sampled" : "exhaustive"; updateSeed(); text.focus(); })); });
      Array.prototype.forEach.call(tabs.children, function (tab) { var selectedTab = tab.getAttribute("data-kind") === kind; tab.setAttribute("aria-selected", String(selectedTab)); tab.tabIndex = selectedTab ? 0 : -1; });
      tabPanel.setAttribute("aria-labelledby", "a2-define-tab-" + kind);
      expression.value = kind === "operation" ? "multiply_preview(13, 17)" : kind === "combinator" ? "@adjust_twice[succ](41)" : kind === "object" ? "ResiduePair(21, 35)" : kind === "observation" ? "?clear_ahead{}" : "mul(13, 17)";
      tree = null; if (boundaryViewer) boundaryViewer.destroy(); boundaryViewer = null; trace.replaceChildren(); useStatus.textContent = writeOnly ? "This browser draft has no core law or bridge check. Build a four-kind preview or use a world atom." : "Run a preview to use its definition, or use a world atom.";
      refreshLibrary(); draw();
    }
    A2.KINDS6.forEach(function (name) {
      tabs.appendChild(el("button", { type: "button", class: "a2-define-tab a2-k-" + name, role: "tab", id: "a2-define-tab-" + name, "aria-controls": "a2-define-tabpanel", "data-kind": name, "aria-selected": "false", tabindex: "-1", onclick: function () { selectKind(name); } }, [A2.icon(name), A2.KIND6_META[name].word]));
    });
    run.addEventListener("click", submit);
    back.addEventListener("click", function () { stop(); frame = Math.max(0, frame - 1); draw(); });
    next.addEventListener("click", function () { stop(); advance(); });
    play.addEventListener("click", function () {
      if (playing) { stop(); return; }
      if (!canAdvance(current, frame)) return;
      if (A2.reducedMotion()) {
        while (canAdvance(current, frame)) { frame++; }
        draw();
        return;
      }
      playing = true; play.textContent = "Pause"; advance();
    });
    tabs.addEventListener("keydown", function (event) {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      var names = A2.KINDS6, position = names.indexOf(kind);
      selectKind(names[event.key === "Home" ? 0 : event.key === "End" ? names.length - 1 : (position + (event.key === "ArrowRight" ? 1 : -1) + names.length) % names.length]);
      tabs.querySelector('[aria-selected="true"]').focus();
    });
    section.addEventListener("keydown", function (event) {
      if (event.target !== section) return;
      if (event.key === "ArrowRight") { event.preventDefault(); next.click(); }
      if (event.key === "ArrowLeft") { event.preventDefault(); back.click(); }
    });

    function use() {
      if (typeof boundaryObserver !== "undefined") {
        if (boundaryObserver) boundaryObserver.disconnect();
        boundaryObserver = null;
      }
      if (boundaryViewer) boundaryViewer.destroy(); boundaryViewer = null;
      tree = null; trace.replaceChildren(); useStatus.textContent = "";
      try {
        var parsed = parse("preview_use = " + expression.value + " L1", "operation"), world = towerWorld || kind === "observation" ? "robot" : "integer";
        var preview = current && current.record && current.record.world === world && current.record.source === text.value &&
          ["previewed", "verified", "evaluated (no reference check)"].includes(current.record.status) ? current.record : null;
        var useLibrary = preview ? library.filter(function (entry) { return entry.world !== world || entry.name !== preview.name; }).concat(preview) : library;
        var outcome = evaluate(parsed, "operation", world, [], useLibrary, { fuel: 300, layer: 1, probes: { front_wall: false, front_water: true } });
        if (!outcome.tree || !outcome.tree.children.length) { tree = null; trace.replaceChildren(visibleValue(outcome.outcome.unknown ? { unknown: outcome.outcome.unknown } : outcome.outcome.bottom ? { bottom: outcome.outcome.bottom } : { ok: outcome.result }, world)); useStatus.textContent = "No derivation is available for this outcome."; return; }
        tree = outcome.tree.children.length === 1 ? outcome.tree.children[0] : outcome.tree;
        if (A2.chargedLeaves(tree) !== outcome.steps) {
          var givenCalls = [], pending = [tree], outsideScope = false;
          while (pending.length) {
            var currentNode = pending.pop();
            outsideScope = outsideScope || !!currentNode.outsideCheckedScope;
            if (currentNode.given) givenCalls.push(currentNode.def);
            else pending.push.apply(pending, currentNode.children || []);
          }
          trace.replaceChildren(el("div", { class: "a2-define-trace-badge" }, [
            el("p", {}, [visibleCall(expression.value, world, useLibrary), " ⇒ ", visibleValue({ ok: outcome.result }, world), ". " + outcome.steps + " charged layer-0 calls."]),
            el("p", {}, [givenCalls.length ? "Actual calls: " : "The body has no given calls.", givenCalls.length ? givenCalls.map(function (name, index) {
              var mark = root.N3Convert.worldLegend(world, mock.defs, useLibrary).find(function (entry) { return entry.name === name; });
              return [index ? ", " : "", mark ? root.N3Convert.render(mark.display) : formula(null, name)];
            }) : null])
          ]));
          useStatus.textContent = (outsideScope ? "Outside checked scope: unfolded from the body. " : "") + "Computed in your browser. The boundary viewer cannot represent a zero-cost body.";
          return;
        }
        if (!A2.boundary || !A2.boundary.render) { useStatus.textContent = "Boundary viewer is unavailable."; return; }
        boundaryViewer = A2.boundary.render(trace, { derivation: { title: "Workshop call", world: world, root: tree }, compact: true });
        displayBoundary(trace, world, tree);
        trace.prepend(el("p", { class: "a2-define-trace-badge" }, [A2.badge("design"), " Computed in your browser from the preview fixture."]));
        function hasOutsideScope(node) { return !!node.outsideCheckedScope || (node.children || []).some(hasOutsideScope); }
        useStatus.textContent = hasOutsideScope(tree) ? "Outside checked scope: previewed calls unfold from their bodies." : "Computed in your browser. Click a step or change the cut to explore the same computation.";
      } catch (error) { useStatus.textContent = "Cannot use this expression: " + error.message; }
    }
    useButton.addEventListener("click", use);
    selectKind("operation");
  }

  A2.define = { tokenize: tokenize, parse: parse, check: check, evaluate: evaluate, verify: verify, pipeline: pipeline, evidenceKey: evidenceKey, canAdvance: canAdvance, presetsFor: presetsFor, storeSession: storeSession, examples: examples };
  A2.register("define", mount);
  if (typeof module !== "undefined" && module.exports) module.exports = A2.define;
})(typeof window !== "undefined" ? window : globalThis);
