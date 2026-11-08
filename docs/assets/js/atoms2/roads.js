(function (root) {
  "use strict";

  function compareLists(left, right) {
    const leftText = left.join(",");
    const rightText = right.join(",");
    return leftText < rightText ? -1 : leftText > rightText ? 1 : 0;
  }

  function closures(graph, budget) {
    if (!Number.isInteger(budget) || budget < 0 || budget > 2) throw new Error("Budget must be 0, 1, or 2");
    const ids = Object.keys(graph.edges).sort();
    const result = [[]];
    if (budget >= 1) ids.forEach(id => result.push([id]));
    if (budget >= 2) ids.forEach((id, index) => ids.slice(index + 1).forEach(next => result.push([id, next])));
    return result;
  }

  function routeCost(graph, vertices, closed = []) {
    if (!Array.isArray(vertices) || vertices.length < 2 ||
        vertices.some(vertex => !graph.nodes.includes(vertex)) || new Set(vertices).size !== vertices.length) return null;
    if (!Array.isArray(closed) || closed.some(id => !Object.hasOwn(graph.edges, id))) return null;
    const blocked = new Set(closed);
    let total = 0;
    for (let index = 1; index < vertices.length; index++) {
      const id = [vertices[index - 1], vertices[index]].sort().join("");
      if (blocked.has(id) || !Object.hasOwn(graph.edges, id)) return null;
      total += graph.edges[id];
    }
    return total;
  }

  function extendMapRoute(graph, route, closed, junction) {
    if (junction === "A") return ["A"];
    if (route.length && junction === route[route.length - 1]) return route.slice(0, -1);
    if (!route.length || route.includes(junction) || !graph.nodes.includes(junction)) return null;
    const road = [route[route.length - 1], junction].sort().join("");
    return Object.hasOwn(graph.edges, road) && !closed.includes(road) ? [...route, junction] : null;
  }

  function closeMapRoad(route, road) {
    const index = route.slice(1).findIndex((junction, position) =>
      [route[position], junction].sort().join("") === road);
    return index < 0 ? route : route.slice(0, index + 1);
  }

  function routes(graph, start, end, closed = []) {
    if (!graph.nodes.includes(start) || !graph.nodes.includes(end) || start === end) throw new Error("Distinct known endpoints required");
    const blocked = new Set(closed);
    const result = [];
    function visit(path, total) {
      const current = path[path.length - 1];
      if (current === end) { result.push({ route: path, cost: total }); return; }
      Object.entries(graph.edges).forEach(([id, weight]) => {
        if (blocked.has(id) || !id.includes(current)) return;
        const next = id[0] === current ? id[1] : id[0];
        if (!path.includes(next)) visit([...path, next], total + weight);
      });
    }
    visit([start], 0);
    return result;
  }

  function shortest(graph, start, end, closed = []) {
    const candidates = routes(graph, start, end, closed);
    candidates.sort((left, right) => left.cost - right.cost || compareLists(left.route, right.route));
    return candidates[0] || null;
  }

  function worst(graph, start, end, budget = 2) {
    let answer = null;
    for (const closed of closures(graph, budget)) {
      const best = shortest(graph, start, end, closed);
      if (!best) return { disconnected: closed };
      if (!answer || best.cost > answer.cost ||
          (best.cost === answer.cost && compareLists(closed, answer.closed) < 0)) {
        answer = { closed, route: best.route, cost: best.cost };
      }
    }
    return answer;
  }

  function mincut(graph, start, end) {
    if (!graph.nodes.includes(start) || !graph.nodes.includes(end) || start === end) throw new Error("Distinct known endpoints required");
    const middle = graph.nodes.filter(node => node !== start && node !== end);
    let answer = null;
    for (let mask = 0; mask < 2 ** middle.length; mask++) {
      const side = new Set([start]);
      middle.forEach((node, index) => { if (mask & (2 ** index)) side.add(node); });
      const cut = Object.keys(graph.edges).filter(id => side.has(id[0]) !== side.has(id[1])).sort();
      if (!answer || cut.length < answer.length ||
          (cut.length === answer.length && compareLists(cut, answer) < 0)) answer = cut;
    }
    return answer;
  }

  function routeIssue(graph, route, closed) {
    if (!Array.isArray(route) || route.length < 2) return "Provide at least two route junctions from A to L.";
    if (route[0] !== "A" || route[route.length - 1] !== "L") return "Route must begin at A and end at L.";
    const unknown = route.find(vertex => !graph.nodes.includes(vertex));
    if (unknown) return "Unknown junction: " + unknown + ".";
    const seen = new Set();
    for (let index = 0; index < route.length; index++) {
      const vertex = route[index];
      if (seen.has(vertex)) return "Repeated junction: " + vertex + ".";
      seen.add(vertex);
      if (!index) continue;
      const road = [route[index - 1], vertex].sort().join("");
      if (!Object.hasOwn(graph.edges, road)) return "No road joins " + route[index - 1] + " and " + vertex + ".";
      if (closed.includes(road)) return "Road " + road + " is closed.";
    }
    return null;
  }

  function judge(graph, closed, route) {
    if (!Array.isArray(closed)) return { correct: false, reason: "Closed roads must be a list of road IDs." };
    if (closed.length > 2) return { correct: false, reason: "At most two roads may close; received " + closed.length + "." };
    if (new Set(closed).size !== closed.length) return { correct: false, reason: "Closed road IDs must be distinct; received " + closed.join(", ") + "." };
    const unknown = closed.filter(id => !Object.hasOwn(graph.edges, id));
    if (unknown.length) return { correct: false, reason: "Unknown road ID: " + unknown.join(", ") + "." };
    const normalized = closed.slice().sort();
    const issue = routeIssue(graph, route, normalized);
    if (issue) {
      const alternative = shortest(graph, "A", "L", normalized);
      return { correct: false, reason: issue,
        counterexample: alternative ? { closed: normalized, ...alternative } : { disconnected: normalized } };
    }
    const cost = routeCost(graph, route, normalized);
    const chosen = shortest(graph, "A", "L", normalized);
    if (cost !== chosen.cost || compareLists(route, chosen.route) !== 0)
      return { correct: false, reason: "A cheaper or lexicographically earlier route exists for your closure.", counterexample: { closed: normalized, ...chosen } };
    const candidate = worst(graph, "A", "L", 2);
    if (candidate.disconnected) return { correct: false, reason: "A closure disconnects the endpoints.", counterexample: candidate };
    if (cost !== candidate.cost || compareLists(normalized, candidate.closed) !== 0) {
      const counterexample = closures(graph, 2).map(failure => ({ closed: failure, ...shortest(graph, "A", "L", failure) }))
        .find(item => item.cost > cost || (item.cost === cost && compareLists(item.closed, normalized) < 0));
      return { correct: false, reason: "This is not the first worst closure.", counterexample };
    }
    return { correct: true, cost, closed: normalized, route, cases: closures(graph, 2).length };
  }

  const junctions = {
    A: [48, 220], B: [165, 60], C: [165, 220], D: [165, 380],
    E: [305, 85], F: [305, 220], G: [305, 365],
    H: [450, 85], I: [450, 220], J: [450, 365], K: [590, 150], L: [660, 315]
  };
  function mapLayout(graph) {
    const occupied = [];
    const segments = Object.keys(graph.edges).map(id => ({ id, from: junctions[id[0]], to: junctions[id[1]] }));
    return Object.entries(graph.edges).map(([id, weight]) => {
      const from = junctions[id[0]];
      const to = junctions[id[1]];
      if (!from || !to) throw new Error("Unknown map road or junction");
      const dx = to[0] - from[0];
      const dy = to[1] - from[1];
      const length = Math.hypot(dx, dy);
      const normal = [-dy / length, dx / length];
      const halfWidth = (id + " " + weight).length * 3.8 + 3;
      const halfHeight = 11;
      let label;
      for (const fraction of [.5, .4, .6, .3, .7, .2, .8]) {
        for (const offset of [16, -16, 24, -24, 32, -32, 40, -40, 48, -48]) {
          const x = from[0] + dx * fraction + normal[0] * offset;
          const y = from[1] + dy * fraction + normal[1] * offset;
          if (x - halfWidth < 4 || x + halfWidth > 716 || y - halfHeight < 4 || y + halfHeight > 436) continue;
          if (occupied.some(box => Math.abs(x - box.x) < halfWidth + box.halfWidth + 4 &&
              Math.abs(y - box.y) < halfHeight + box.halfHeight + 4)) continue;
          if (Object.values(junctions).some(node => Math.hypot(x - node[0], y - node[1]) < 22 + halfWidth * .25)) continue;
          if (segments.some(segment => {
            if (segment.id === id) return false;
            const segmentDx = segment.to[0] - segment.from[0];
            const segmentDy = segment.to[1] - segment.from[1];
            let entry = 0;
            let exit = 1;
            for (const [origin, distance, minimum, maximum] of [
              [segment.from[0], segmentDx, x - halfWidth, x + halfWidth],
              [segment.from[1], segmentDy, y - halfHeight, y + halfHeight]
            ]) {
              if (distance === 0) {
                if (origin < minimum || origin > maximum) return false;
              } else {
                entry = Math.max(entry, Math.min((minimum - origin) / distance, (maximum - origin) / distance));
                exit = Math.min(exit, Math.max((minimum - origin) / distance, (maximum - origin) / distance));
              }
            }
            return (exit - entry) * Math.hypot(segmentDx, segmentDy) > 2;
          })) continue;
          label = [x, y];
          break;
        }
        if (label) break;
      }
      if (!label) throw new Error("No room for road label " + id);
      occupied.push({ x: label[0], y: label[1], halfWidth, halfHeight });
      return { id, weight, from, to, label };
    });
  }

  function roadsEvidence(data, graph, href) {
    if (data.status !== "design") throw new Error("Unexpected road fixture status");
    const edgeWeights = Object.values(graph.edges);
    const maxSimpleCost = (graph.nodes.length - 1) * Math.max(...edgeWeights);
    if (!Number.isSafeInteger(maxSimpleCost)) throw new Error("Road costs exceed exact integer range");
    return {
      evidence: {
        method: "browser enumeration (not v2 verification)",
        scope: {domain: "road closures of size 0, 1, or 2", size: closures(graph, 2).length,
          description: "Design record. Browser computation enumerates closures and simple routes; costs are exact integers from 0 to " + maxSimpleCost + "."}
      },
      artifact: {file: "docs/assets/data/atoms2/roads.json", href}
    };
  }

  function roadExpression(text, options = {}) {
    const expression = root.A2.expr(text, { ...options, world: options.world || "roads" });
    Array.from(expression.childNodes).forEach(child => {
      if (child.nodeType !== 3 || !child.textContent.includes(",")) return;
      const parts = child.textContent.split(",");
      const nodes = [];
      parts.forEach((part, index) => {
        nodes.push(document.createTextNode(index < parts.length - 1 ? part + "," : part));
        if (index < parts.length - 1) nodes.push(document.createElement("wbr"));
      });
      child.replaceWith(...nodes);
    });
    return expression;
  }

  function layerPrefix(layer) { return layer === 0 ? "" : "L" + layer + " "; }

  function towerLayers(tower) {
    const entries = new Map(tower.map(item => [item.name, item]));
    if (entries.size !== tower.length) throw new Error("Duplicate road definition");
    const layers = new Map();
    const visiting = new Set();
    function layerOf(name) {
      if (layers.has(name)) return layers.get(name);
      const item = entries.get(name);
      if (!item) throw new Error("Unknown road dependency " + name);
      if (visiting.has(name)) throw new Error("Cyclic road dependency " + name);
      visiting.add(name);
      const parents = item.depends_on.map(layerOf);
      const given = item.declaration.endsWith(" given");
      if (given && parents.length) throw new Error("Given road definition has dependencies: " + name);
      const layer = given ? 0 : 1 + Math.max(0, ...parents);
      visiting.delete(name);
      layers.set(name, layer);
      return layer;
    }
    return tower.map(item => {
      const layer = layerOf(item.name);
      return { ...item, layer, storedDeclaration: item.declaration, declaration: layer === 0 ? item.declaration :
        item.declaration.replace(/ L\d+$/, " L" + layer) };
    }).sort((left, right) => left.layer - right.layer);
  }

  function observationDesignIssue(item, tower) {
    if (item.kind !== "observation" || item.declaration.endsWith(" given")) return "";
    const entries = new Map(tower.map(entry => [entry.name, entry]));
    const proposed = item.depends_on.filter(name => entries.get(name)?.kind !== "observation");
    return proposed.length ? "Proposed dependencies: " + proposed.join(", ") +
      ". Spec 0.5 permits pure definitions on observed values; whether these qualify needs a checked roads world." : "";
  }

  function coreResult(card) {
    const outcome = card.example.outcome;
    var description = "ok" in outcome ? "Succeeded" : "Stopped";
    if ("ok" in outcome && outcome.ok.t === "List") description += " with " + outcome.ok.f.length +
      (card.name === "failures" ? " closures" : " routes");
    return description + " in " + card.example.steps + " layer-0 steps";
  }

  function coreBadge(card, href) {
    const evidence = card.evidence || {};
    return root.A2.scopedBadge(evidence, null,
      { file: "docs/assets/data/atoms2/roads_core.json", href: href });
  }

  function coreRunLabel(card) {
    return !root.A2.hasRecordedScope(card.evidence) ? "Core run on Metro (scope not recorded)" :
      card.example.outside_checked_scope ? "Core run on Metro (outside the checked scope)" : "Core run on Metro";
  }

  function coreRoadEvidence(core, graph) {
    const cards = new Map(core.cards.map(card => [card.name, card]));
    const asked = ["A", "D", "F", "H", "K", "L"];
    const best = shortest(graph, "A", "L");
    const value = cards.get("best").example.outcome.ok;
    const coreBest = value.f[0].f[1].f.map(node => node.v);
    const coreCut = cards.get("mincut").example.outcome.ok.f[0].f.map(road => road.v);
    const checks = {
      asked_cost: cards.get("cost").example.outcome.ok.v === routeCost(graph, asked),
      best: compareLists(coreBest, best.route) === 0 && routeCost(graph, coreBest) === best.cost,
      optimal: cards.get("optimal").example.outcome.ok.tag === "false" && routeCost(graph, asked) > best.cost,
      survives: (cards.get("survives").example.outcome.ok.tag === "true") ===
        closures(graph, 2).every(closed => shortest(graph, "A", "L", closed) !== null),
      mincut: compareLists(coreCut, mincut(graph, "A", "L")) === 0,
      cut_certificate: cards.get("cut_certificate").example.outcome.ok.tag === "true" &&
        coreCut.length === 3 && closures(graph, 2).every(closed => shortest(graph, "A", "L", closed) !== null) &&
        shortest(graph, "A", "L", coreCut) === null,
      missing_road: core.failing.outcome.bottom === "invalid" && routeCost(graph, ["A", "E", "L"]) === null
    };
    if (Object.values(checks).some(agrees => !agrees)) throw new Error("Metro browser and core results disagree");
    return checks;
  }

  function dependencyRows(tower, names) {
    const entries = new Map(tower.map(item => [item.name, item]));
    return names.map(name => {
      const item = entries.get(name);
      if (!item) throw new Error("Unknown road definition " + name);
      item.depends_on.forEach(parent => {
        if (!entries.has(parent)) throw new Error("Unknown road dependency " + parent);
      });
      return { name, depends_on: [...item.depends_on] };
    });
  }

  function label(text, kind, layer) { return root.A2.token(text, { kind, origin: layer ? "invented" : "given", layer, world: "roads" }); }
  function appendDependencyRow(container, row, items, button) {
    const entry = document.createElement("li");
    entry.dataset.name = row.name;
    const item = items.get(row.name);
    if (button) entry.append(button);
    else entry.append(label(row.name, item.kind, item.layer));
    const prerequisites = document.createElement("span");
    prerequisites.className = "roads-prerequisites";
    prerequisites.append("Uses: ");
    row.depends_on.forEach((name, index) => {
      if (index) prerequisites.append(", ");
      const parent = items.get(name);
      const token = label(name, parent.kind, parent.layer);
      token.dataset.prerequisite = name;
      prerequisites.append(token);
    });
    if (!row.depends_on.length) prerequisites.append("none (given)");
    entry.append(prerequisites);
    container.append(entry);
  }
  const Roads = { compareLists, closures, routeCost, extendMapRoute, closeMapRoad, routes, shortest, worst, mincut, routeIssue, judge, mapLayout, bindWitness, redrawPathKeepingFocus, setMapZoom, roadsEvidence, coreRoadEvidence, roadExpression, layerPrefix, towerLayers, observationDesignIssue, dependencyRows, appendDependencyRow };
  if (typeof module !== "undefined" && module.exports) module.exports = Roads;
  root.A2Roads = Roads;

  if (typeof document === "undefined") return;
  const dataUrl = new URL("../../data/atoms2/roads.json", document.currentScript.src);
  const coreUrl = new URL("../../data/atoms2/roads_core.json", document.currentScript.src);
  function edgeIds(route) {
    return route.slice(1).map((node, index) => [route[index], node].sort().join(""));
  }
  function svgElement(name, attributes, text) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function drawMap(graph, container, options = {}) {
    const svg = svgElement("svg", { viewBox: "0 0 720 440", role: "img", "aria-label": options.interactive ?
      "Metro graph. Use the map controls or text fields to choose closed roads and an A-to-L route." :
      "Metro graph: asked route A,D,F,H,K,L costs 12; best route A,D,G,I,K,L costs 11." });
    const roadElements = new Map();
    const nodeElements = new Map();
    const labels = svgElement("g", { class: "roads-labels", "aria-hidden": "true" });
    mapLayout(graph).forEach(({ id, weight, from, to, label: position }) => {
      const group = svgElement("g", { class: "roads-edge" });
      group.append(svgElement("line", { x1: from[0], y1: from[1], x2: to[0], y2: to[1], class: "roads-edge-line" }));
      if (options.interactive) group.append(svgElement("line", { x1: from[0], y1: from[1], x2: to[0], y2: to[1], class: "roads-edge-hit" }));
      if (options.interactive) {
        group.setAttribute("aria-hidden", "true");
        group.addEventListener("click", () => options.onRoad(id));
      }
      const halfWidth = (id + " " + weight).length * 3.8 + 3;
      const labelGroup = svgElement("g", { class: options.interactive ? "roads-label-control" : "" });
      labelGroup.append(svgElement("rect", { x: position[0] - halfWidth, y: position[1] - 11,
        width: halfWidth * 2, height: 22, rx: 4, class: "roads-label-chip" }));
      labelGroup.append(svgElement("text", { x: position[0], y: position[1], class: "roads-edge-label" }, id + " " + weight));
      if (options.interactive) labelGroup.addEventListener("click", () => options.onRoad(id));
      labels.append(labelGroup);
      svg.append(group);
      roadElements.set(id, group);
    });
    svg.append(labels);
    graph.nodes.forEach(id => {
      const group = svgElement("g", { class: "roads-node" });
      if (options.interactive) {
        group.setAttribute("aria-hidden", "true");
        group.addEventListener("click", () => options.onNode(id));
      }
      group.append(svgElement("circle", { cx: junctions[id][0], cy: junctions[id][1], r: 16 }));
      group.append(svgElement("text", { x: junctions[id][0], y: junctions[id][1] }, id));
      svg.append(group);
      nodeElements.set(id, group);
    });
    container.replaceChildren(svg);
    const roadButtons = new Map();
    const nodeButtons = new Map();
    if (options.interactive) {
      const details = document.createElement("details");
      details.className = "roads-map-keyboard";
      const summary = document.createElement("summary");
      summary.textContent = "Map controls: roads and junctions";
      const controls = document.createElement("div");
      controls.className = "roads-map-controls";
      controls.setAttribute("role", "group");
      controls.setAttribute("aria-label", "Metro map keyboard controls");
      Object.entries(graph.edges).forEach(([id, weight]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Road " + id + " (" + weight + ")";
        button.setAttribute("aria-label", "Toggle road " + id + ", weight " + weight);
        button.addEventListener("click", () => options.onRoad(id));
        controls.append(button);
        roadButtons.set(id, button);
      });
      graph.nodes.forEach(id => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Junction " + id;
        button.addEventListener("click", () => options.onNode(id));
        controls.append(button);
        nodeButtons.set(id, button);
      });
      details.append(summary, controls);
      container.append(details);
    }
    return function update({ closed = [], route = [], best = [] }) {
      const routeEdges = new Set(edgeIds(route));
      const bestEdges = new Set(edgeIds(best));
      roadElements.forEach((group, id) => {
        group.classList.toggle("is-closed", closed.includes(id));
        group.classList.toggle("is-route", routeEdges.has(id));
        group.classList.toggle("is-best", bestEdges.has(id));
        if (options.interactive) roadButtons.get(id).setAttribute("aria-pressed", String(closed.includes(id)));
      });
      nodeElements.forEach((group, id) => {
        group.classList.toggle("is-route", route.includes(id));
        group.classList.toggle("is-best", best.includes(id));
        if (options.interactive) {
          nodeButtons.get(id).setAttribute("aria-pressed", String(route.includes(id)));
          nodeButtons.get(id).setAttribute("aria-label", "Junction " + id + (route.at(-1) === id ? ", last in route" : route.includes(id) ? ", in route" : ""));
        }
      });
    };
  }
  function fieldsToList(field) { return field.value.trim().toUpperCase().split(/[\s,]+/).filter(Boolean); }
  function bindWitness(closedField, routeField, report, syncMap) {
    function changed(announce = true) {
      const note = syncMap();
      if (announce) report.textContent = typeof note === "string" && note ? note : "Answer changed. Check again.";
    }
    closedField.addEventListener("input", changed);
    routeField.addEventListener("input", changed);
    return changed;
  }
  function redrawPathKeepingFocus(path, rows, render) {
    const active = path.ownerDocument.activeElement;
    const focusedName = path.contains(active) && active.closest("button[data-name]")?.dataset.name;
    path.replaceChildren();
    rows.forEach(render);
    if (focusedName) {
      const replacement = Array.from(path.querySelectorAll("button[data-name]")).find(button => button.dataset.name === focusedName);
      if (replacement) replacement.focus();
    }
  }
  function setMapZoom(container, button, cue, zoomed) {
    container.classList.toggle("is-zoomed", zoomed);
    container.scrollLeft = 0;
    button.setAttribute("aria-pressed", String(zoomed));
    button.textContent = zoomed ? "Fit whole map" : "Zoom in on map";
    cue.textContent = zoomed ? "Swipe the map sideways to see every road, or fit the whole map." :
      "The whole map, from A to L, is shown. Zoom in to read road labels.";
  }
  function mount(data, core) {
    if (root.N3) [data, core].forEach(item => { if (item && item.notation3) root.N3.register(item.notation3); });
    if (root.N3 && root.N3.legendPanel && (data.notation3 || core && core.notation3)) {
      document.querySelectorAll("[data-roads-home], [data-roads-learn], [data-roads-challenge]").forEach(host => {
        host.appendChild(root.N3.legendPanel("roads"));
      });
    }
    const graph = data.graph;
    const tower = towerLayers(data.tower);
    const givenNames = tower.filter(item => item.layer === 0).map(item => item.name);
    const record = roadsEvidence(data, graph, dataUrl.pathname);
    const coreCards = core && new Map(core.cards.map(card => [card.name, card]));
    if (core && (document.querySelector("[data-roads-home]") || document.querySelector("[data-roads-learn]"))) {
      coreRoadEvidence(core, graph);
    }
    document.querySelectorAll("[data-roads-badge]").forEach(placeholder => {
      placeholder.replaceWith(core ? coreBadge(core.cards[0], coreUrl.pathname) : root.A2.badge("design", {record}));
    });
    const home = document.querySelector("[data-roads-home]");
    if (home) {
      const steps = ["Route", "cost", "@explore", "best", "?optimal"];
      const items = new Map(tower.map(item => [item.name, item]));
      const panel = home.querySelector("[data-roads-step]");
      const stepStatus = document.createElement("p");
      stepStatus.setAttribute("role", "status");
      stepStatus.className = "a2-visually-hidden";
      panel.after(stepStatus);
      const chain = home.querySelector("[data-roads-chain]");
      const bestRoute = shortest(graph, "A", "L");
      const askedRoute = ["A", "D", "F", "H", "K", "L"];
      const updateMap = drawMap(graph, home.querySelector("[data-roads-map]"));
      const descriptions = [
        "The asked route succeeds. " + coreResult(coreCards.get("Route")) + ".",
        "The asked route costs 12. " + coreResult(coreCards.get("cost")) + ".",
        "The exploration enumerates simple routes. " + coreResult(coreCards.get("explore")) + ".",
        "The cheapest route " + bestRoute.route.join(",") + " costs " + bestRoute.cost + ". " + coreResult(coreCards.get("best")) + ".",
        "The route is valid but not optimal: false. " + coreResult(coreCards.get("optimal")) + "."
      ].map((description, position) => coreRunLabel(coreCards.get(steps[position].replace(/^[?@]/, ""))) + ": " + description);
      let index = 0;
      let timer;
      steps.forEach((step, position) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "roads-chain-step";
        button.setAttribute("aria-label", "Definition " + (position + 1) + ": " + step);
        const item = tower.find(entry => entry.name === step);
        button.append(label(step, item.kind, item.layer));
        button.addEventListener("click", () => { index = position; render(); pause(); stepStatus.textContent = "Step " + (index + 1) + ": " + descriptions[index]; });
        chain.append(button);
      });
      steps.forEach(name => {
        const card = coreCards.get(name.replace(/^[?@]/, ""));
        const row = document.createElement("li");
        row.append(label(name, card.kind, card.layer), " Uses: " + (card.invented_dependencies.join(", ") || "given atoms") + ".",
          root.A2.el("p", {}, ["Definition evidence: ", coreBadge(card, coreUrl.pathname)]),
          root.A2.el("p", {}, [root.A2.expr(card.example.call, { world: "roads" }), " ",
            root.A2.runBadge(card.example, "assets/data/atoms2/roads_core.json"),
            ". " + coreRunLabel(card) + ": " + coreResult(card) + "."]));
        home.querySelector("[data-roads-home-deps]").append(row);
      });
      function render() {
        panel.textContent = descriptions[index];
        chain.querySelectorAll("button").forEach((button, position) => {
          button.classList.toggle("is-current", position === index);
          if (position === index) button.setAttribute("aria-current", "step"); else button.removeAttribute("aria-current");
        });
        home.querySelector("[data-roads-position]").textContent = (index + 1) + " / " + steps.length;
        home.querySelector("[data-roads-answer]").hidden = index !== steps.length - 1;
        home.querySelector("[data-roads-result]").hidden = index !== steps.length - 1;
        home.querySelector("[data-roads-next]").disabled = index === steps.length - 1;
        updateMap({ route: askedRoute, best: index === steps.length - 1 ? bestRoute.route : [] });
      }
      const play = home.querySelector("[data-roads-play]");
      const next = home.querySelector("[data-roads-next]");
      function pause() {
        clearInterval(timer);
        timer = null;
        play.textContent = index === steps.length - 1 ? "Replay recorded steps" : "Play recorded steps";
      }
      function advance() {
        if (index < steps.length - 1) index++;
        render();
        if (index === steps.length - 1) {
          if (timer) stepStatus.textContent = "Road steps complete. " + descriptions[index];
          pause();
        }
      }
      next.addEventListener("click", () => { pause(); advance(); stepStatus.textContent = "Step " + (index + 1) + ": " + descriptions[index]; });
      const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reducedMotion) play.hidden = true;
      play.addEventListener("click", () => {
        if (timer) { pause(); return; }
        if (index === steps.length - 1) { index = 0; render(); }
        play.textContent = "Pause recorded steps";
        stepStatus.textContent = "Playing five recorded road steps.";
        timer = setInterval(advance, 520);
      });
      home.querySelector("[data-roads-result]").textContent = "Core run: asked cost 12; best cost 11; the asked route is not optimal. " +
        "Independently computed in your browser: asked cost " + routeCost(graph, askedRoute) +
        "; best cost " + bestRoute.cost + ".";
      const optimalText = coreCards.get("optimal")?.example.call;
      const optimalSlot = home.querySelector("[data-roads-optimal]");
      if (optimalText && optimalSlot) optimalSlot.replaceWith(roadExpression(optimalText, {given: givenNames}));
      render();
    }
    const learn = document.querySelector("[data-roads-learn]");
    if (learn) {
      const list = learn.querySelector("[data-roads-layers]");
      list.replaceChildren();
      const givenList = learn.querySelector("[data-roads-given-layers]");
      const failures = closures(graph, 2);
      tower.forEach(item => {
        const coreCard = coreCards.get(item.name.replace(/^[?@]/, ""));
        if (coreCard) item = { ...item, layer: coreCard.layer };
        const card = document.createElement("li");
        card.dataset.name = item.name;
        const button = document.createElement("button"); button.type = "button";
        button.append(layerPrefix(item.layer), label(item.name, item.kind, item.layer));
        const role = document.createElement("span"); role.className = "roads-role";
        button.append(role);
        button.addEventListener("click", () => highlight(item.name));
        const desc = document.createElement("p");
        const segments = root.N3 && root.N3.prose(item.description, "roads");
        if (segments) segments.forEach(segment => desc.append(segment[0] === "f" ? root.N3.render(segment[1], segment[2]) : document.createTextNode(segment[1])));
        else desc.textContent = item.description;
        const issue = coreCard ? "" : observationDesignIssue(item, tower);
        if (issue) desc.append(" " + issue);
        // Notation v3 entries are keyed by the stored declaration (its layer may differ).
        const stored = root.N3 && root.N3.lookup(item.storedDeclaration, "roads") ? item.storedDeclaration : item.declaration;
        const declaration = roadExpression(stored, {given: givenNames, design: !(root.N3 && root.N3.lookup(stored, "roads"))});
        card.append(button, coreCard ? coreBadge(coreCard, "../assets/data/atoms2/roads_core.json") :
          root.A2.badge("design", {record}), desc, coreCard && coreCard.declaration_label.startsWith("placeholder (") ?
            root.A2.el("p", {class: "w2-design-text", text: "No source published for this definition."}) :
            coreCard ? roadExpression(coreCard.declaration, {given: givenNames}) : declaration);
        if (coreCard) card.append(document.createTextNode(coreCard.declaration_label + ". "),
          root.A2.expr(coreCard.example.call, { world: "roads" }), root.A2.runBadge(coreCard.example, "../assets/data/atoms2/roads_core.json"),
          document.createTextNode(". " + coreRunLabel(coreCard) + ": " + coreResult(coreCard) + "."));
        (item.layer === 0 ? givenList : list).append(card);
      });
      const path = learn.querySelector("[data-roads-path]");
      const survivalButton = learn.querySelector("[data-roads-survives]");
      function highlight(name, announce = true) {
        const selectedCore = new Set();
        function visit(key) {
          const canonical = key.replace(/^[?@]/, "").split(".")[0];
          if (selectedCore.has(canonical)) return;
          selectedCore.add(canonical);
          const card = coreCards.get(canonical);
          if (card) card.invented_dependencies.forEach(visit);
        }
        visit(name);
        const coreRows = core.cards.filter(card => selectedCore.has(card.name));
        redrawPathKeepingFocus(path, coreRows, card => {
          const button = document.createElement("button");
          button.type = "button";
          button.dataset.name = card.display_name;
          button.append(layerPrefix(card.layer), label(card.display_name, card.kind, card.layer));
          button.addEventListener("click", () => highlight(card.display_name));
          const row = document.createElement("li");
          row.append(button, " Uses: " + (card.dependencies.join(", ") || "given atoms") + ".",
            root.A2.el("p", {}, ["Definition evidence: ", coreBadge(card, "../assets/data/atoms2/roads_core.json")]),
            root.A2.el("p", {}, [root.A2.expr(card.example.call, { world: "roads" }), " ",
              root.A2.runBadge(card.example, "../assets/data/atoms2/roads_core.json"),
              ". " + coreRunLabel(card) + ": " + coreResult(card) + "."]));
          path.append(row);
        });
        if (!coreRows.length) {
          const designed = tower.find(item => item.name === name);
          if (designed) {
            const row = document.createElement("li");
            row.append(label(name, designed.kind, designed.layer), " Uses: " +
              (designed.depends_on.join(", ") || "given atoms") + ". ",
              root.A2.badge("design", {record}));
            path.append(row);
          }
        }
        learn.querySelectorAll(".roads-layers li").forEach(card => {
          const isTarget = card.dataset.name === name;
          const isPrerequisite = selectedCore.has(card.dataset.name.replace(/^[?@]/, "")) && !isTarget;
          card.classList.toggle("is-required", isPrerequisite);
          card.classList.toggle("is-selected", isTarget);
          card.querySelector("button").setAttribute("aria-pressed", String(isTarget));
          card.querySelector(".roads-role").textContent = isTarget ? "Target" : isPrerequisite ? "Prerequisite" : "";
        });
        const description = "Selected target: " + name + ". Invented prerequisites shown: " +
          [...selectedCore].filter(key => key !== name.replace(/^[?@]/, "")).join(", ") +
          ". " + failures.length + " closures at budget 2." +
          (coreCards.has(name.replace(/^[?@]/, "")) ? " Core run: " + coreResult(coreCards.get(name.replace(/^[?@]/, ""))) + "." : " Designed example; no core run for this card.") +
          (name === "?survives" ? " Independently computed in your browser: " + failures.every(closed => shortest(graph, "A", "L", closed) !== null) + "." : "");
        learn.querySelector("[data-roads-deps]").textContent = announce ? description : "Select a definition to see its prerequisites.";
        survivalButton.textContent = name === "?survives" ? "Hide survival prerequisites" : "Show survival prerequisites";
        survivalButton.setAttribute("aria-pressed", String(name === "?survives"));
      }
      function clearSelection() {
        path.replaceChildren();
        learn.querySelectorAll(".roads-layers li").forEach(card => {
          card.classList.remove("is-required", "is-selected");
          card.querySelector("button").setAttribute("aria-pressed", "false");
          card.querySelector(".roads-role").textContent = "";
        });
        learn.querySelector("[data-roads-deps]").textContent = "Select a definition or show survival prerequisites to see direct dependencies.";
        survivalButton.textContent = "Show survival prerequisites";
        survivalButton.setAttribute("aria-pressed", "false");
      }
      survivalButton.addEventListener("click", () => survivalButton.getAttribute("aria-pressed") === "true" ? clearSelection() : highlight("?survives"));
      highlight("?survives", false);
    }
    const video = document.querySelector("#opulse-video video");
    if (video) {
      let theme;
      function syncTheme() {
        const chosen = document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "light";
        if (theme === chosen) return;
        theme = chosen;
        video.poster = video.dataset[chosen + "Poster"];
        video.querySelector('source[type="video/webm"]').src = video.dataset[chosen + "Webm"];
        video.querySelector('source[type="video/mp4"]').src = video.dataset[chosen + "Mp4"];
        video.load();
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) video.pause();
        else video.play().catch(() => {});
      }
      new MutationObserver(syncTheme).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
      syncTheme();
    }
    const challenge = document.querySelector("[data-roads-challenge]");
    if (challenge) {
      const zoomButton = challenge.querySelector("[data-roads-zoom]");
      const mapContainer = challenge.querySelector("[data-roads-map]");
      const zoomCue = challenge.querySelector("[data-roads-map-cue]");
      zoomButton.addEventListener("click", () => setMapZoom(mapContainer, zoomButton, zoomCue,
        zoomButton.getAttribute("aria-pressed") !== "true"));
      const report = challenge.querySelector("[data-roads-report]");
      const closedField = challenge.querySelector('input[name="closed"]');
      const routeField = challenge.querySelector('input[name="route"]');
      let changed;
      function announceMap(note = "") {
        const route = fieldsToList(routeField);
        const closed = fieldsToList(closedField);
        report.textContent = note + "Route: " + (route.join(", ") || "none") + ". Closed roads: " + (closed.join(", ") || "none") + ". Check again.";
      }
      const updateMap = drawMap(graph, mapContainer, {
        interactive: true,
        onRoad(id) {
          const closed = fieldsToList(closedField);
          let note = "";
          if (closed.includes(id)) closedField.value = closed.filter(item => item !== id).join(", ");
          else if (closed.length < 2) closedField.value = [...closed, id].join(", ");
          else { report.textContent = "Choose at most two closed roads. Reopen one before selecting another."; return; }
          if (!closed.includes(id)) {
            const route = fieldsToList(routeField);
            const remaining = closeMapRoad(route, id);
            if (remaining.length !== route.length) {
              routeField.value = remaining.join(", ");
              note = "Route shortened because road " + id + " closed. ";
            }
          }
          changed(false); announceMap(note);
        },
        onNode(id) {
          const route = fieldsToList(routeField);
          const next = extendMapRoute(graph, route, fieldsToList(closedField), id);
          if (!next) { report.textContent = "Start at A, then choose an adjacent unvisited junction along an open road. Click the last junction to undo it."; return; }
          routeField.value = next.join(", ");
          changed(false); announceMap();
        }
      });
      function syncMap() {
        const closed = fieldsToList(closedField);
        const route = fieldsToList(routeField);
        const openRoute = closed.reduce((remaining, id) => closeMapRoad(remaining, id), route);
        if (openRoute.length !== route.length) routeField.value = openRoute.join(", ");
        updateMap({ closed, route: openRoute });
        return openRoute.length !== route.length ? "Route shortened because a selected road is closed. Check again." : "";
      }
      changed = bindWitness(closedField, routeField, report, syncMap);
      challenge.querySelector("[data-roads-edge-list]").textContent = Object.entries(graph.edges)
        .map(([id, weight]) => id + ": " + weight).join("; ") + ".";
      syncMap();
      challenge.querySelector("form").addEventListener("submit", event => {
        event.preventDefault();
        const closed = fieldsToList(closedField);
        const route = fieldsToList(routeField);
        const result = judge(graph, closed, route);
        report.textContent = result.correct ? "Correct. Cost " + result.cost + "; all " + result.cases + " closures inspected in your browser." :
          "Incorrect. " + result.reason + (result.counterexample ? result.counterexample.route ? " Counterexample: Edges<" + result.counterexample.closed.join(",") + ">, Route<" + result.counterexample.route.join(",") + ">, cost " + result.counterexample.cost + "." : " Disconnecting closure: Edges<" + result.counterexample.disconnected.join(",") + ">." : "");
      });
      challenge.querySelector("[data-roads-reveal]").addEventListener("click", event => {
        const target = challenge.querySelector("[data-roads-all]");
        target.hidden = !target.hidden;
        event.currentTarget.setAttribute("aria-expanded", String(!target.hidden));
        if (target.hidden) return;
        const answer = worst(graph, "A", "L");
        const checks = closures(graph, 2).map(closed => ({ closed, best: shortest(graph, "A", "L", closed) }));
        const counts = checks.map(check => check.best.cost);
        target.textContent = "Computed in your browser: " + counts.length + " cases (1 empty, 23 single, 253 double). " +
          "All have a route; minimum shortest cost " + Math.min(...counts) + ", maximum " + Math.max(...counts) +
          ". First maximum: Edges<" + answer.closed.join(",") + ">, Route<" + answer.route.join(",") + ">. " +
          "Minimum separating cut: Edges<" + mincut(graph, "A", "L").join(",") + ">.";
        const list = document.createElement("ol");
        list.className = "roads-case-list";
        checks.forEach(check => {
          const item = document.createElement("li");
          item.textContent = "Edges<" + check.closed.join(",") + ">: cost " + check.best.cost +
            ", Route<" + check.best.route.join(",") + ">";
          list.append(item);
        });
        target.append(list);
      });
      const params = new URLSearchParams(window.location.search);
      if (params.has("closed") || params.has("route")) {
        closedField.value = params.get("closed") || "";
        routeField.value = params.get("route") || "";
        syncMap();
        if (params.get("check") === "1") challenge.querySelector("form").requestSubmit();
      }
      if (params.get("reveal") === "1") challenge.querySelector("[data-roads-reveal]").click();
    }
  }
  function init() {
    if (!document.querySelector("[data-roads-home], [data-roads-learn], [data-roads-challenge]")) return;
    const needsCore = document.querySelector("[data-roads-home], [data-roads-learn]");
    Promise.all([fetch(dataUrl).then(response => { if (!response.ok) throw new Error("Road data unavailable"); return response.json(); }),
      needsCore ? fetch(coreUrl).then(response => { if (!response.ok) throw new Error("Road core run unavailable"); return response.json(); }) : Promise.resolve(null)])
      .then(([data, core]) => mount(data, core)).catch(() => {
        document.querySelectorAll("[data-roads-step], [data-roads-layers], [data-roads-report]").forEach(element => {
          element.textContent = "Road data unavailable. Reload to try again.";
        });
      });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
}(typeof window !== "undefined" ? window : globalThis));
