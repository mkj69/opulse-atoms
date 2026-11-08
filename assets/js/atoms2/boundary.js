(function (root) {
  "use strict";
  var A2 = root.A2 || (root.A2 = {});

  function traceFixture(derivations) {
    return { derivations: derivations, charged: A2.chargedLeaves,
      find: function (name, world) {
        var found = null;
        Object.keys(derivations).some(function (key) {
          var trace = derivations[key];
          if (world && trace.world !== world) return false;
          var definition = definitions(trace.root).filter(function (item) { return item.name === name; })[0];
          if (!definition) return false;
          found = definition;
          return true;
        });
        return found;
      } };
  }

  function isKernelTrace(rootNode) {
    var data = A2.kernelData || {};
    return [data.derivations, data.modes && data.modes.derivations].some(function (derivations) {
      return derivations && Object.keys(derivations).some(function (key) {
        return derivations[key].root === rootNode;
      });
    });
  }

  function cut(rootNode, boundary) {
    if (!rootNode) return [];
    var selected = A2.boundary(boundary);
    var rows = [];
    function visit(node, depth, parentId) {
      if (!node) return;
      var children = node.children || [];
      var given = !!node.given || (!node.emptyBody && children.length === 0);
      var opened = !given && (!!node.containsOutsideCheckedScope || A2.isOpened(node, selected));
      rows.push({ id: node.id, path: (node.path || []).slice(), def: node.def, kind: node.kind,
        layer: node.layer, given: given, depth: depth, args: node.args, result: node.result,
        folded: !opened && !given, opened: opened, charged: A2.chargedLeaves(node), parentId: parentId,
        outsideScope: !!node.containsOutsideCheckedScope });
      if (opened) children.forEach(function (child) { visit(child, depth + 1, node.id); });
    }
    visit(rootNode, 0, null);
    return rows;
  }

  function definitions(rootNode) {
    var found = {};
    function visit(node) {
      if (!node) return;
      if (!found[node.def]) found[node.def] = { name: node.def, kind: node.kind, layer: node.layer, given: node.given || (!node.emptyBody && !(node.children || []).length) };
      (node.children || []).forEach(visit);
    }
    visit(rootNode);
    return Object.keys(found).map(function (name) { return found[name]; }).sort(function (left, right) {
      return right.layer - left.layer || left.name.localeCompare(right.name);
    });
  }

  function tour(rootNode) {
    var folded = definitions(rootNode).reduce(function (max, def) { return Math.max(max, def.layer); }, 0) + 1;
    return [[A2.chargedLeaves(rootNode) ? "Fold all: one visible step." : "Fold all: no charged steps.", { depth: folded }],
      [A2.chargedLeaves(rootNode) ? "Open this call: reveal its immediate steps." : "Open this call: body has no given calls.", { depth: folded, open_paths: [[]] }],
      ["Unfold to layer 0.", { depth: 1 }]].map(function (entry) {
      return { caption: entry[0], boundary: A2.boundary(entry[1]) };
    });
  }

  function boundaryText(boundary, maxLayer) {
    var parts = [];
    if (boundary.depth !== maxLayer) parts.push("depth=" + boundary.depth);
    if (boundary.open_names.length) parts.push("open_names={" + boundary.open_names.join(", ") + "}");
    if (boundary.keep_names.length) parts.push("keep_names={" + boundary.keep_names.join(", ") + "}");
    if (boundary.open_paths.length) parts.push("open_paths={" + boundary.open_paths.map(function (path) { return "(" + path.join(", ") + ")"; }).join(", ") + "}");
    if (boundary.kinds.length !== A2.ALL_KINDS.length) parts.push("kinds={" + boundary.kinds.join(", ") + "}");
    return "Boundary(" + parts.join(", ") + ")";
  }

  function graphLayout(defs, rootNode) {
    var layers = Array.from(new Set(defs.map(function (def) { return def.layer; }))).sort(function (a, b) { return b - a; });
    var positions = {}, bands = [], top = 12;
    layers.forEach(function (layer) {
      var group = defs.filter(function (def) { return def.layer === layer; });
      var height = 24 + Math.ceil(group.length / 3) * 43;
      bands.push({ layer: layer, top: top, height: height });
      group.forEach(function (def, index) { positions[def.name] = { x: 52 + (index % 3) * 112, y: top + 35 + Math.floor(index / 3) * 43 }; });
      top += height;
    });
    var links = [], seen = {};
    function visit(node) {
      if (!node) return;
      (node.children || []).forEach(function (child) {
        var key = node.def + ":" + child.def;
        if (!seen[key] && node.def !== child.def && positions[node.def] && positions[child.def]) {
          links.push({ from: node.def, to: child.def }); seen[key] = true;
        }
        visit(child);
      });
    }
    visit(rootNode);
    return { positions: positions, bands: bands, links: links, height: top + 8 };
  }

  function mount(host, mock, supplied) {
    if (root.N3 && A2.kernelData && A2.kernelData.notation3) root.N3.register(A2.kernelData.notation3);
    function atomToken(name, kind, layer, given, world) {
      return root.N3 && !(typeof root.N3.name === "function" ? root.N3.name(name, world, kind) :
        root.N3.lookup(name, world)) ? el("span", { text: "No source published" }) :
        A2.token(name, { kind: kind, layer: layer, origin: given ? "given" : "invented", world: world });
    }
    function resultValue(result, world, opened) {
      var machine = A2.formatValue(result, { world: world });
      if (root.N3 && typeof root.N3.value === "function" && root.N3.value(result, world))
        return A2.value(result, { world: world });
      return root.N3 && root.N3.lookup(machine, world) ? A2.expr(machine, { world: world }) :
        opened ? el("span", { text: machine }) : A2.value(result, { world: world });
    }
    var el = A2.el;
    var keys = Object.keys((mock && mock.derivations) || {});
    if (!keys.length) { host.textContent = "No derivations available."; return { destroy: function () { host.replaceChildren(); } }; }
    var settings = supplied || {};
    if (settings.derivation && keys.indexOf(settings.derivation) < 0) console.warn("Unavailable boundary derivation: " + settings.derivation);
    var current = keys.indexOf(settings.derivation) >= 0 ? settings.derivation : keys[0];
    var rootNode = mock.derivations[current].root;
    var kernelBacked = isKernelTrace(rootNode);
    var maxLayer, states, index, custom = null, playing = false, timer, flashTimer, previousRows = [], destroyed = false;

    function snapshot() { return A2.boundary(custom || states[index].boundary); }
    function restoreFocus(container, key) {
      if (!key) return false;
      var control = Array.prototype.find.call(container.querySelectorAll('[data-boundary-control]'), function (node) {
        return node.getAttribute("data-boundary-control") === key;
      });
      if (!control || control.disabled) return false;
      control.focus();
      return true;
    }
    function stop() {
      playing = false;
      clearTimeout(timer);
      playButton.textContent = "Play";
      playButton.setAttribute("aria-label", "Play boundary steps");
    }
    function reset() {
      stop();
      kernelBacked = isKernelTrace(rootNode);
      maxLayer = definitions(rootNode).reduce(function (max, item) { return Math.max(max, item.layer || 0); }, 0) + 1;
      states = tour(rootNode);
      index = states.length > 1 ? 1 : 0;
      custom = null;
      previousRows = [];
      draw();
    }
    function commit(next) {
      stop();
      custom = A2.boundary(next);
      draw();
    }
    function forward() {
      if (custom) { custom = null; index = 0; draw(); return true; }
      if (index >= states.length - 1) return false;
      index++; draw(); return true;
    }
    function tick() {
      if (!playing || destroyed) return;
      if (!forward()) { stop(); return; }
      timer = setTimeout(tick, 1150);
    }

    var picker = el("select", { class: "a2-boundary-select", "aria-label": "Choose derivation" }, keys.map(function (key) {
      return el("option", { value: key, text: mock.derivations[key].title });
    }));
    picker.value = current;
    picker.addEventListener("change", function () { if (destroyed) return; current = picker.value; rootNode = mock.derivations[current].root; reset(); });
    var slider = el("input", { type: "range", step: 1, "aria-label": "Unfold depth" });
    var depthText = el("strong", { class: "a2-boundary-depth-value" });
    slider.addEventListener("input", function () { var next = snapshot(); next.depth = Number(slider.value); commit(next); });
    var kinds = el("div", { class: "a2-boundary-kinds" });
    var record = el("span", { class: "a2-boundary-record" });
    var result = el("span", { class: "a2-boundary-result" });
    var charged = el("strong");
    var shown = el("strong");
    var check = el("span", { class: "a2-boundary-check", text: "OK Unchanged" });
    var graph = el("div", { class: "a2-boundary-graph" });
    var list = el("div", { class: "a2-boundary-list", role: "group", "aria-label": "Derivation steps", tabindex: "0" });
    var counter = el("span", { class: "a2-boundary-counter", "aria-live": "polite" });
    var caption = el("p", { class: "a2-boundary-caption", "aria-live": "polite" });
    var backButton = el("button", { class: "a2-btn", type: "button", "aria-label": "Previous boundary cut", text: "Back", onclick: function () {
      stop(); if (custom) { custom = null; draw(); } else if (index > 0) { index--; draw(); }
    } });
    var playButton = el("button", { class: "a2-btn", type: "button", "aria-label": "Play boundary steps", text: "Play", onclick: function () {
      if (playing) { stop(); return; }
      if (A2.reducedMotion()) {
        custom = null;
        index = index === states.length - 1 ? Math.min(1, states.length - 1) : states.length - 1;
        draw(); return;
      }
      if (!custom && index === states.length - 1) { index = 0; draw(); }
      playing = true; playButton.textContent = "Pause"; playButton.setAttribute("aria-label", "Pause boundary steps"); tick();
    } });
    var nextButton = el("button", { class: "a2-btn", type: "button", "aria-label": "Next boundary cut", text: "Next", onclick: function () { stop(); forward(); } });
    host.classList.add("a2-boundary");
    if (settings.compact) host.classList.add("a2-boundary-compact");
    A2.append(host, [
      el("div", { class: "a2-boundary-intro" }, [el("span", { class: "a2-boundary-eyebrow", text: "ATOM BOUNDARY / INTERACTIVE TRACE" }),
        el("p", { text: "Same computation. Different visible steps." }),
        A2.badge(kernelBacked ? "executable" : "design",
          kernelBacked ? { artifact: "docs/assets/js/atoms2/data.js" } : {})]),
      el("div", { class: "a2-boundary-controls a2-panel" }, [
        el("div", { class: "a2-boundary-control-head" }, [
          el("label", { class: "a2-boundary-picker" }, [el("span", { text: "Derivation" }), picker]),
          el("div", { class: "a2-boundary-transport" }, [backButton, playButton, nextButton, counter])]),
        el("div", { class: "a2-boundary-depth" }, [
          el("label", { text: "Unfold down from layer " }), depthText,
          slider, el("div", { class: "a2-boundary-scale" }, [el("span", { text: "Layer 0" }), el("span", { text: "Fold all" })])]),
        el("div", { class: "a2-boundary-kind-group" }, [el("span", { text: "Unfold by kind" }), kinds]),
        el("div", { class: "a2-boundary-record-line" }, [el("span", { text: "Current cut" }), record,
          el("button", { class: "a2-btn", type: "button", text: "Reset", "aria-label": "Reset boundary", onclick: reset })])
      ]),
      el("div", { class: "a2-boundary-invariants a2-panel", "aria-label": "Boundary invariants" }, [
        el("div", { class: "a2-boundary-metric a2-boundary-pinned" }, [el("span", { text: "RESULT / PINNED" }), result]),
        el("div", { class: "a2-boundary-metric" }, [el("span", { text: "LAYER-0 STEPS CHARGED" }), charged]),
        el("div", { class: "a2-boundary-metric" }, [el("span", { text: "STEPS SHOWN" }), shown]), check
      ]),
      caption,
      el("div", { class: "a2-boundary-workspace" }, [
        el("section", { class: "a2-boundary-graph-panel a2-panel" }, [
          el("h3", { text: "Definition graph" }), el("p", { text: "Given = world atoms  /  ring = open  /  dashed line = cut; filled chip = given, outlined chip = invented" }), graph]),
        el("section", { class: "a2-boundary-trace a2-panel" }, [
          el("div", { class: "a2-boundary-trace-head" }, [el("h3", { text: "Evaluation trace" }), el("span", { text: "Click a step to change the cut" })]), list])
      ])
    ]);
    function onKeydown(event) {
      if (event.target === picker || event.target === slider || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "ArrowRight") { event.preventDefault(); stop(); forward(); }
      if (event.key === "ArrowLeft") { event.preventDefault(); stop(); if (custom) { custom = null; draw(); } else if (index > 0) { index--; draw(); } }
      if (event.key === " " && event.target === list) { event.preventDefault(); playButton.click(); }
    }
    host.addEventListener("keydown", onKeydown);

    function draw() {
      var focused = root.document && root.document.activeElement;
      var focusKey = focused && focused.getAttribute && focused.getAttribute("data-boundary-control");
      var selected = snapshot();
      var rows = cut(rootNode, selected);
      var protectedNames = {}, protectedKinds = {};
      function findProtected(node) {
        if (node.containsOutsideCheckedScope) { protectedNames[node.def] = true; protectedKinds[node.kind] = true; }
        (node.children || []).forEach(findProtected);
      }
      findProtected(rootNode);
      slider.min = 1; slider.max = maxLayer; slider.value = selected.depth;
      depthText.textContent = String(selected.depth);
      counter.textContent = custom ? "custom" : "Step " + (index + 1) + " / " + states.length;
      caption.textContent = (custom ? "Custom cut: change depth, position, or kind to explore." : states[index].caption) +
        (Object.keys(protectedNames).length ? " Outside checked scope: affected calls must remain unfolded; their kind and definition controls are unavailable." : "");
      nextButton.textContent = custom ? "Restart tour" : "Next";
      nextButton.setAttribute("aria-label", custom ? "Restart boundary tour" : "Next boundary cut");
      backButton.disabled = !custom && index === 0;
      nextButton.disabled = !custom && index === states.length - 1;
      record.textContent = boundaryText(selected, maxLayer);
      kinds.replaceChildren();
      A2.ALL_KINDS.forEach(function (kind) {
        var enabled = selected.kinds.indexOf(kind) !== -1;
        kinds.appendChild(el("button", { class: "a2-boundary-kind a2-k-" + kind, type: "button",
          "aria-label": protectedKinds[kind] ? kind + " calls outside checked scope must remain unfolded" : (enabled ? "Stop unfolding " : "Unfold ") + kind + "s", "aria-pressed": String(enabled),
          "data-boundary-control": "kind:" + kind, disabled: !!protectedKinds[kind],
          title: protectedKinds[kind] ? "Outside checked scope: calls must remain unfolded" : "",
          onclick: function () {
            var next = snapshot();
            next.kinds = enabled ? next.kinds.filter(function (item) { return item !== kind; }) : A2.ALL_KINDS.filter(function (item) { return next.kinds.indexOf(item) !== -1 || item === kind; });
            commit(next);
          } }, [A2.icon(kind), "Unfold " + kind + "s"]));
      });
      var resultText = A2.formatValue(rootNode.result);
      if (resultText.length > 44 && resultText.indexOf(", ") !== -1) {
        var wrapped = el("span", { class: "a2-v a2-v-result a2-boundary-wrapped-value" });
        resultText.split(/(, )/).forEach(function (part) {
          if (part) wrapped.appendChild(el("span", { text: part }));
          if (part === ", ") wrapped.appendChild(el("wbr"));
        });
        result.replaceChildren(wrapped);
      } else result.replaceChildren(A2.value(rootNode.result, { role: "result" }));
      charged.textContent = mock.charged(rootNode);
      shown.textContent = rows.filter(function (row) { return (row.folded || row.given) && row.charged > 0; }).length;
      if (previousRows.length) {
        check.classList.remove("a2-boundary-pulse"); void check.offsetWidth;
        check.classList.add("a2-boundary-pulse");
      }
      var defs = definitions(rootNode);
      var layout = graphLayout(defs, rootNode);
      var oldCut = graph.querySelector(".a2-boundary-graph-cut");
      var oldTop = oldCut ? oldCut.style.top : null;
      var stage = el("div", { class: "a2-boundary-graph-stage", style: "height:" + layout.height + "px" });
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "a2-boundary-edges");
      svg.setAttribute("viewBox", "0 0 360 " + layout.height);
      svg.setAttribute("aria-hidden", "true");
      layout.links.forEach(function (link) {
        var from = layout.positions[link.from], to = layout.positions[link.to];
        var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", "M " + from.x + " " + (from.y + 14) + " C " + from.x + " " + ((from.y + to.y) / 2) + ", " + to.x + " " + ((from.y + to.y) / 2) + ", " + to.x + " " + (to.y - 16));
        svg.appendChild(path);
      });
      stage.appendChild(svg);
      layout.bands.forEach(function (band) {
        stage.appendChild(el("span", { class: "a2-boundary-layer-label", style: "top:" + band.top + "px", text: band.layer === 0 ? "Given" : "L" + band.layer,
          title: band.layer === 0 ? "Given world atoms" : "Layer " + band.layer }));
      });
      defs.forEach(function (def) {
        var visible = rows.filter(function (row) { return row.def === def.name; });
        var open = visible.some(function (row) { return row.opened; }) && !visible.some(function (row) { return row.folded; });
        var position = layout.positions[def.name];
        stage.appendChild(el("button", { type: "button", class: "a2-boundary-node a2-k-" + def.kind + (open ? " is-open" : ""), style: "left:" + (position.x - 50) + "px;top:" + (position.y - 16) + "px",
          "aria-label": def.given ? def.name + ", given atom" : protectedNames[def.name] ? def.name + ", outside checked scope, must remain unfolded" : (open ? "Keep " : "Unfold ") + def.name + " everywhere", "aria-pressed": String(open),
          "data-boundary-control": "node:" + def.name, disabled: def.given || !!protectedNames[def.name], title: def.given ? "Given atom" : protectedNames[def.name] ? "Outside checked scope: calls must remain unfolded" : open ? "Keep this definition folded everywhere" : "Unfold this definition everywhere",
          onclick: function () {
            if (def.given) return;
            var next = snapshot();
            if (open) {
              if (next.keep_names.indexOf(def.name) === -1) next.keep_names.push(def.name);
              next.open_names = next.open_names.filter(function (name) { return name !== def.name; });
            } else {
              next.keep_names = next.keep_names.filter(function (name) { return name !== def.name; });
              if (next.open_names.indexOf(def.name) === -1) next.open_names.push(def.name);
              if (next.kinds.indexOf(def.kind) === -1) next.kinds.push(def.kind);
            }
            commit(next);
          } }, atomToken(def.name, def.kind, def.layer, def.given, mock.derivations[current].world)));
      });
      var openedLayers = rows.filter(function (row) { return row.opened; }).map(function (row) { return row.layer; });
      var lowest = openedLayers.length ? Math.min.apply(null, openedLayers) : Infinity;
      var band = layout.bands.filter(function (item) { return item.layer === lowest; })[0];
      var cutTop = band ? band.top + band.height - 12 : 8;
      var cutLine = el("div", { class: "a2-boundary-graph-cut", style: "top:" + (oldTop || cutTop + "px") }, [el("span", { text: "CUT" })]);
      stage.appendChild(cutLine);
      graph.replaceChildren(stage);
      if (focusKey && focusKey.indexOf("node:") === 0) restoreFocus(graph, focusKey);
      if (focusKey && focusKey.indexOf("kind:") === 0) restoreFocus(kinds, focusKey);
      if (oldTop && !A2.reducedMotion()) root.requestAnimationFrame(function () { cutLine.style.top = cutTop + "px"; });
      else cutLine.style.top = cutTop + "px";
      clearTimeout(flashTimer);
      var prior = {};
      previousRows.forEach(function (row) { prior[row.id] = row; });
      var changed = {};
      rows.forEach(function (row) { if (prior[row.id] && prior[row.id].folded && row.opened) changed[row.id] = true; });
      var reveal = {}, arrival = 0;
      var rowsById = {};
      rows.forEach(function (row) { rowsById[row.id] = row; });
      rows.forEach(function (row) {
        if (!prior[row.id]) {
          var parent = row.parentId;
          while (parent && !changed[parent]) parent = rowsById[parent] ? rowsById[parent].parentId : null;
          if (parent) reveal[row.id] = Math.min(240, row.depth * 30 + arrival++ * 14);
        }
      });
      A2.flip(list, function () {
        list.replaceChildren();
        rows.forEach(function (row) {
          var def = Object.assign({ name: row.def, kind: row.kind, layer: row.layer },
            mock.find(row.def, mock.derivations[current].world), { given: row.given });
          var button = el(row.given ? "div" : "button", { class: "a2-boundary-row a2-k-" + row.kind + (row.opened ? " is-header" : "") + (changed[row.id] ? " is-focus" : "") + (reveal[row.id] !== undefined ? " is-new" : ""),
            type: row.given ? undefined : "button", "data-flip": row.id, "data-boundary-control": row.given ? undefined : "row:" + row.id, style: "--a2-boundary-indent:" + (Math.min(row.depth, 8) * 9) + "px;--a2-boundary-delay:" + (reveal[row.id] || 0) + "ms",
            disabled: !!row.outsideScope, title: row.outsideScope ? "Outside checked scope: call must remain unfolded" : row.opened ? "Keep this definition folded everywhere" : row.folded ? "Unfold this call at this position" : "Given atom",
            "aria-label": row.given ? row.def + ", given atom" : row.outsideScope ? row.def + ", outside checked scope, must remain unfolded" : row.opened ? "Keep " + row.def + " folded everywhere" : "Unfold " + row.def + " at this position",
            onclick: row.given ? undefined : function () {
              var next = snapshot();
              if (row.opened) {
                if (next.keep_names.indexOf(row.def) === -1) next.keep_names.push(row.def);
                next.open_names = next.open_names.filter(function (name) { return name !== row.def; });
              } else {
                next.keep_names = next.keep_names.filter(function (name) { return name !== row.def; });
                if (!next.open_paths.some(function (path) { return A2.pathKey(path) === A2.pathKey(row.path); })) next.open_paths.push(row.path);
                if (next.kinds.indexOf(row.kind) === -1) next.kinds.push(row.kind);
              }
              commit(next);
            } }, [
              el("span", { class: "a2-boundary-mark", "aria-hidden": "true", text: row.given ? "." : row.opened ? "[" : "]" }),
              atomToken(def.name, def.kind, def.layer, row.given, mock.derivations[current].world), A2.badge(kernelBacked ? "executable" : "design",
                kernelBacked ? { artifact: "docs/assets/js/atoms2/data.js" } : {}),
              el("span", { class: "a2-boundary-expression" }, [el("span", { class: "a2-boundary-args", text: "(" + (row.args || []).map(A2.formatValue).join(", ") + ")" }), el("span", { class: "a2-boundary-arrow", text: " -> " }), resultValue(row.result, mock.derivations[current].world, row.opened)]),
              el("span", { class: "a2-boundary-row-status", text: row.given ? "given" : row.charged === 0 ? "invented / 0 steps" : row.opened ? "open" : "folded  /  " + row.charged + " steps" })
            ]);
          list.appendChild(button);
        });
        if (focusKey && focusKey.indexOf("row:") === 0 && !restoreFocus(list, focusKey)) list.focus();
        rows.forEach(function (row) {
          if (!row.opened) return;
          var descendants = rows.filter(function (candidate) { return candidate.path.length > row.path.length && row.path.every(function (part, index) { return candidate.path[index] === part; }); });
          var last = descendants[descendants.length - 1];
          if (!last) return;
          var header = list.querySelector('[data-flip="' + row.id + '"]');
          var end = list.querySelector('[data-flip="' + last.id + '"]');
          header.style.setProperty("--a2-boundary-branch", (end.offsetTop + end.offsetHeight - header.offsetTop - 14) + "px");
        });
      }, { ms: 220, stagger: 48 });
      previousRows = rows;
      flashTimer = setTimeout(function () { if (!destroyed) list.querySelectorAll(".is-focus, .is-new").forEach(function (node) { node.classList.remove("is-focus", "is-new"); }); }, 1650);
    }
    reset();
    return { destroy: function () {
      if (destroyed) return;
      destroyed = true; stop(); clearTimeout(flashTimer);
      host.removeEventListener("keydown", onKeydown);
      host.replaceChildren();
      host.classList.remove("a2-boundary", "a2-boundary-compact", "a2-boundary-embedded");
    } };
  }

  A2.boundary.cut = cut;
  A2.boundary.definitions = definitions;
  A2.boundary.tour = tour;
  A2.boundary.graphLayout = graphLayout;
  A2.boundary.format = boundaryText;
  A2.boundary.render = function (host, settings) {
    settings = settings || {};
    var derivation = settings.derivation;
    if (!host || !derivation || !derivation.root) return { destroy: function () {} };
    return mount(host, traceFixture({ custom: derivation }), { derivation: "custom", compact: !!settings.compact });
  };
})(typeof window !== "undefined" ? window : globalThis);
