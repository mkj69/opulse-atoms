(function (root) {
  "use strict";
  var SCOPE = {
    action: ["First local scan in a sealed 12x10 maze", "Scan up to 25 cells", "Explore 60 reachable cells and record collisions", "Transfer a controller to a second maze", "Reject an unreachable target under a fuel cap"],
    circuits: ["Two inputs and up to 12 gates", "Three inputs and 22 gates", "Carry chain with up to 16 inputs", "Four-bit multiplication and accumulation", "Compare circuits on up to 65,536 input rows"],
    dice: ["One fair die and one event", "Two dice and 36 ordered outcomes", "Condition on successive hidden observations", "Plan over 8 to 40 turns", "Solve a finite hitting-time system exactly"],
    integer: ["Integers through 20, loop bound 8", "Integers through 200, loop bound 60", "Continued fractions of depth 4 to 7", "Depth 8 to 12 with explicit fuel", "Depth 12 to 24 over a finite answer domain"],
    pixels: ["8x8 image, one transform", "12x12 image with holes", "16x16 image and eight orientations", "24x24 image with composed transforms", "32x32 image with hundreds of candidates"],
    rhythm: ["8 to 12 beats, one voice", "Two voices and two accents", "Cycles of length 12 and 16", "Cycles of length 15 and 16 with perturbations", "Cycles up to 512 beats and inverse phase search"],
    shadows: ["One slice and four mask cells", "Two slices with up to 49 candidates", "Four slices with 2,401 candidates", "Six slices with a large candidate set", "Bounded search over 200,000 candidates"],
    versions: ["Two branches with one commit each", "Transactions with multiple guarded changes", "Three to five concurrent conflicts", "Replay five to eight commits", "Resolve 12 to 24 commits across three branches"],
    automata: ["Two small machines and short words", "Product of up to 330 states", "Refine a partition across reachable states", "Search longer distinguishing words", "Bound search over 2,000 reachable states"],
    grammar: ["One to three digits with addition", "Up to six digits and nested parentheses", "Seven to nine digits with cached parse counts", "Ten to twelve digits and frequency tables", "Up to 48 tokens and bounded depth eight"],
    hidden: ["One public signal and two lamp colors", "Two modes with a public action cost", "Six-round visible histories and policy trees", "Invert a posterior over nine observations", "Dynamic programming over 4,096 visible histories"],
    lists: ["Lists up to length six with empty failures", "Length 16 with repeated and negative values", "Length 40 with inversion counts", "Length 128 with bounded trace output", "Length 512 with explicit certificate limits"],
    molecules: ["Trees with up to three heavy atoms", "Four heavy atoms and one ring", "Five heavy atoms and canonical forms", "Six heavy atoms with one cycle", "Inverse search with up to 32 candidate formulas"],
    permutation: ["Four active positions and two swaps", "Six positions with disjoint cycles", "Explore an orbit of up to 128 states", "Ten positions and up to 1,024 states", "Twelve positions and a group of up to 4,096 states"],
    calendar: ["One date without holidays", "One month with leap-day handling", "Cross two years with observed holidays", "Sixteen months and month-end settlement", "A hundred-year finite date search"],
    geometry: ["One polygon on a 33x33 grid", "One hole and two transformations", "Two holes and four transformations", "Three holes and dihedral transforms", "Multiple regions with a bounded grid-point search"],
    kitchen: ["Two ingredients and four ticks", "Four ingredients with mixer and oven", "Three product types over eight ticks", "Four stations and ten ticks", "Invert a recipe over a bounded ingredient stock"],
    melody: ["Eight notes and two motifs", "Sixteen notes across an octave", "Thirty-two notes with nested motifs", "Forty-eight notes and several tonal regions", "Sixty-four notes with overlapping motifs"],
    roads: ["12 junctions, 23 roads, one valid route", "419 simple A-to-L routes and tie breaks", "At most two closures: 277 candidate failure sets", "Up to 16 junctions and three closures", "Up to 20 junctions with explicit size and fuel caps"],
    text: ["Eight codepoints and a tiny lexicon", "Sixteen codepoints and weighted alternatives", "Thirty-two codepoints and word segmentation", "Forty-eight codepoints and inverse weights", "Sixty-four codepoints with lexicon edits"],
    computer: ["Finite 8-bit registers", "Memory reads under a fixed program", "Modular dot product versus wide accumulation", "Compare paired states with one byte changed", "Prove a bounded machine invariant"]
  };
  var PITCH = {
    action: "The exported case uses three corridor cells. The 12x10 sealed maze below is a separate design.",
    circuits: "Build XOR using only AND and NOT gates.",
    dice: "Invent independent rolls instead of listing 36 outcomes.",
    integer: "Build multiplication from successors, then define fractions.",
    pixels: "The historical export stores a pixel-grid case. The island-growth question below is a separate design.",
    rhythm: "Shift one accent to change an entire rhythm.",
    shadows: "The same shadow can hide different structures.",
    versions: "Turn competing edits into inspectable conflicts.",
    automata: "Run two small machines together to recognize new words.",
    grammar: "One visible sentence can have different parse trees.",
    hidden: "Use signal lights to plan a guess without seeing the state.",
    lists: "Build a list, then invent a way to fold it.",
    molecules: "Respect each atom's bonds before assembling new molecules.",
    permutation: "Compose swaps and count the steps back to the start.",
    calendar: "Step through February to uncover year rules.",
    geometry: "Close three strokes to define an interior and direction.",
    kitchen: "Every cooking step must have enough ingredients.",
    melody: "Answer one phrase with another using pitch and duration.",
    roads: "Compare a shortest route with a core-run three-road cut and its recorded check scope.",
    text: "Split a character stream into possible words.",
    comb_obs: "Schedule a closed warehouse using combinators and authorized observations.",
    comb_only: "Resolve scheduling conflicts with combinators alone.",
    obj_only: "Construct exact root atlases from sealed polynomial representations.",
    obj_op: "Represent periodic schedules and compute blackout windows.",
    obs_only: "Navigate a blind corridor by inventing observations alone.",
    op_only: "Explore relation networks using operations alone.",
    computer: "The historical export runs a finite machine case. The 16-pair dot product below is a separate design."
  };
  function path(node, suffix) {
    return new URL(node.dataset.root + suffix, root.location.href).href;
  }
  function loadBridges(index, base, fetcher) {
    var file = typeof index.bridges === "string" ? index.bridges : index.bridges && index.bridges.file;
    if (!/^bridges\/[A-Za-z0-9_-]+\.json$/.test(file || "")) file = "bridges/bridges.json";
    return fetcher(base + file).then(function (response) {
      if (!response.ok) throw Error("Bridge export unavailable");
      return response.json();
    }).then(function (exported) {
      if (!Array.isArray(exported.story)) throw Error("Invalid bridge export");
      if (root.N3) root.N3.register(exported.notation3);
      return { story: exported.story, available: true };
    }).catch(function () { return { story: [], available: false }; });
  }
  function bridgeNotice(bridges) {
    return bridges.available ? "" : "Bridge export not available. Cross-world bridge records are not shown.";
  }
  function bridgeVersionMismatch(bridge, exports) {
    var scope = bridge.evidence && bridge.evidence.scope || {};
    var names = [bridge.source_world, bridge.target_world];
    var hashes = [scope.source_world_hash || bridge.evidence && bridge.evidence.world_hash,
      scope.target_world_hash || (names[0] === names[1] && bridge.evidence && bridge.evidence.world_hash)];
    return names.flatMap(function (name, index) {
      var publishedHash = exports && name && exports[name.split("@")[0]];
      return publishedHash && hashes[index] && hashes[index] !== publishedHash ?
        [{ world: name, evidence: hashes[index], published: publishedHash }] : [];
    }).filter(function (entry, index, all) {
      return all.findIndex(function (other) { return other.world === entry.world; }) === index;
    });
  }
  function node(tag, value, className) {
    return root.A2.el(tag, { class: className || "", text: value == null ? "not recorded" : value });
  }
  function displayTitle(world) {
    return world.world === "roads" ? "Road routes and a core-run cut" :
      world.world === "action" ? "Robot probes: corridor export and maze design" : world.title;
  }
  function proseNode(tag, value, world, className) {
    var segments = root.N3 && root.N3.prose(value, world);
    if (!segments) return node(tag, value, className);
    var element = root.A2.el(tag, { class: className || "" });
    segments.forEach(function (segment) {
      element.appendChild(segment[0] === "f" ? root.N3.render(segment[1], segment[2]) :
        root.document.createTextNode(segment[1]));
    });
    return element;
  }
  function designBrief(design, world) {
    var A2 = root.A2, card = A2.el("div", { class: "w2-design-brief" });
    card.appendChild(node("p", "Goal: " + design.goal, "w2-intro"));
    card.appendChild(A2.el("p", {}, [node("strong", "Inputs: "), proseNode("span", design.inputs, world)]));
    card.appendChild(A2.el("p", {}, [node("strong", "Output: "), proseNode("span", design.output, world)]));
    card.appendChild(node("h3", "Rules and tie breaks"));
    var rules = A2.el("ol");
    design.rules.forEach(function (rule) { rules.appendChild(proseNode("li", rule, world)); });
    card.appendChild(rules);
    var full = A2.el("details", { class: "w2-fixture" });
    full.appendChild(node("summary", "Full design prompt"));
    full.appendChild(proseNode("p", design.prompt, world));
    card.appendChild(full);
    return card;
  }
  function recordedAnswer(entry) {
    for (var field of ["answer", "result", "outcome", "expected"]) {
      if (entry[field] !== undefined && entry[field] !== null) return { field: field, value: entry[field] };
    }
    return null;
  }
  function publishedShowcases(card, world, source) {
    var entries = Array.isArray(world.showcase) ? world.showcase : [];
    entries.forEach(function (entry) { card.appendChild(showcaseEntry(entry, source, world.world)); });
    if (entries.length) card.appendChild(root.A2.el("a", { href: source,
      text: "Inspect published fixtures and recorded checks in world export" }));
    return entries.length;
  }
  function showcaseEntry(entry, source, world) {
    var A2 = root.A2, card = A2.el("article", { class: "w2-spotlight" });
    card.appendChild(node("h3", "Published " + (entry.angle || "showcase") + " question"));
    if (typeof entry.prompt === "string" && entry.prompt.trim()) card.appendChild(proseNode("p", entry.prompt, world));
    var answer = recordedAnswer(entry);
    if (answer) {
      var recordedScope = entry.check_scope || entry.scope;
      var scopeText = recordedScope && recordedScope !== "unrecorded" ?
        (typeof recordedScope === "string" ? recordedScope : JSON.stringify(recordedScope)) : "scope not recorded";
      var checkStatus = entry.answer_checked === true ? (recordedScope && recordedScope !== "unrecorded" ?
        "Answer check recorded. " : "Answer recorded; check scope not recorded. ") :
        entry.answer_checked === false ? "Answer check recorded as false. " : "No answer check recorded. ";
      var status = node("p", "Answer (" + answer.field + "). " + checkStatus +
        "Recorded method: " + A2.worlds.ascii(entry.check_method || "method not recorded") +
        ". Recorded scope: " + A2.worlds.ascii(scopeText) + ". ", "w2-eyebrow");
      status.appendChild(A2.el("a", { href: source, text: "Historical export" }));
      card.appendChild(status);
      card.appendChild(typeof answer.value === "string" ?
        (root.N3 && root.N3.lookup(answer.value, world) ? A2.expr(answer.value, { world: world }) :
          proseNode("p", answer.value, world)) : root.N3 ? A2.value(answer.value, { world: world }) :
          A2.expr(JSON.stringify(answer.value)));
    } else card.appendChild(node("p", entry.answer_checked === true ?
      "The export marks answer_checked but stores no answer" :
      "No answer recorded in this export; no answer check is displayed.", "w2-muted"));
    return card;
  }
  function choice(label, values, current, display) {
    var select = root.A2.el("select", { "aria-label": label });
    select.appendChild(root.A2.el("option", { value: "", text: "All " + label.toLowerCase() }));
    values.forEach(function (value) {
      select.appendChild(root.A2.el("option", { value: value, text: display ? display(value) : value }));
    });
    select.value = current || "";
    return select;
  }
  function modalities(world) {
    return root.A2.worlds.tagField(world, "modalities") || world.design && world.design.modalities || null;
  }
  function openKindsSet(world) {
    var kinds = root.A2.worlds.openKinds(world);
    return kinds ? root.A2.KINDS6.filter(function (kind) { return kinds.includes(kind); }).join(",") : null;
  }
  function openKindsLabel(value) {
    var kinds = value.split(",");
    var primary = ["object", "operation", "combinator", "observation"];
    var allFour = primary.every(function (kind) { return kinds.includes(kind); });
    var extras = ["law", "bridge"].filter(function (kind) { return kinds.includes(kind); });
    var label = allFour ? "all four kinds" + (extras.length ? " + " + extras.join(" + ") : "") :
      primary.concat(extras).filter(function (kind) { return kinds.includes(kind); }).join(" + ");
    return kinds.length === 1 ? label + " only" : label;
  }
  function filterWorlds(worlds, filters) {
    return worlds.filter(function (world) {
      var search = [world.title, world.world, PITCH[world.world] || "", world.story &&
        world.story.map(function (entry) { return entry.name + " " + entry.kind; }).join(" "),
        world.design && world.design.tower && world.design.tower.map(function (entry) {
          return entry.name + " " + entry.decl;
        }).join(" "), root.A2.worlds.tagValue(root.A2.worlds.tags(world))].join(" ").toLowerCase();
      return (!filters.q || search.includes(filters.q.toLowerCase())) &&
        (!filters.wave || String(world.wave) === filters.wave) &&
        (!filters.status || root.A2.worlds.status(world) === filters.status) &&
        (!filters.kind || root.A2.worlds.kindCounts(world)[filters.kind] > 0 ||
          (root.A2.worlds.openKinds(world) || []).includes(filters.kind)) &&
        (!filters.tags || (root.A2.worlds.tagField(world, "tags") || []).includes(filters.tags)) &&
        (!filters.open_kinds_set || openKindsSet(world) === filters.open_kinds_set) &&
        root.A2.worlds.fields.every(function (field) {
          var value = field === "open_kinds" ? root.A2.worlds.openKinds(world) : root.A2.worlds.tagField(world, field);
          if (field === "modalities") value = modalities(world);
          return !filters[field] || (Array.isArray(value) ? value.includes(filters[field]) :
            root.A2.worlds.tagValue(value) === filters[field]);
        });
    });
  }
  function visibleWorlds(matches, filters, expanded) {
    return expanded || Object.values(filters).some(Boolean) ? matches : matches.slice(0, 9);
  }
  function openKindsBadge(world) {
    var kinds = openKindsSet(world);
    if (kinds === null) return node("span", "open kinds: not recorded", "w2-open-kinds w2-pending");
    return node("span", "open kinds: " + (kinds ? openKindsLabel(kinds) : "none recorded"), "w2-open-kinds");
  }
  function cardTags(world, featuredKind) {
    var A2 = root.A2;
    var full = A2.worlds.fieldChips(world);
    full.className += " w2-card-all-tags";
    full.id = "w2-tags-" + world.world;
    var summary = A2.el("div", { class: "w2-tags w2-card-tags-summary" });
    Array.from(full.children).forEach(function (chip) {
      if (/^(domain|modalities|star kind): /.test(chip.textContent)) {
        summary.appendChild(node("span", chip.textContent, "w2-tag"));
      }
    });
    if (featuredKind && !A2.worlds.tagField(world, "star_kind")) {
      summary.appendChild(node("span", "featured kind: " + A2.worlds.tagValue(featuredKind), "w2-tag"));
    }
    if (!summary.children.length) summary.appendChild(node("span", "tags pending", "w2-tag w2-pending"));
    var count = full.children.length;
    var button = A2.el("button", { type: "button", class: "w2-card-tags-toggle",
      "aria-controls": full.id, "aria-expanded": "false", text: "Show all " + count + " tags" });
    button.hidden = count <= summary.children.length;
    button.addEventListener("click", function () {
      var expanded = button.getAttribute("aria-expanded") !== "true";
      button.setAttribute("aria-expanded", String(expanded));
      button.textContent = expanded ? "Show fewer tags" : "Show all " + count + " tags";
      full.setAttribute("data-expanded", String(expanded));
      summary.hidden = expanded;
    });
    return [summary, full, button];
  }
  function expandWorlds(cards, draw) {
    var previouslyVisible = cards.querySelectorAll("h2 a").length;
    draw();
    var firstNewLink = cards.querySelectorAll("h2 a")[previouslyVisible];
    if (firstNewLink) firstNewLink.focus();
  }
  function catalog(mount, worlds) {
    if (root.N3) worlds.forEach(function (world) { root.N3.register(world.notation3); });
    var A2 = root.A2, filters = new URLSearchParams(root.location.search);
    var bar = A2.el("div", { class: "w2-filters", role: "search", "aria-label": "Filter worlds" });
    var search = A2.el("input", { type: "search", placeholder: "Search worlds and tower definitions", "aria-label": "Search worlds and tower definitions", value: filters.get("q") || "" });
    var openKindValues = A2.KINDS6.filter(function (kind) {
      return worlds.some(function (world) { return (A2.worlds.openKinds(world) || []).includes(kind); });
    });
    var controls = { q: search,
      open_kinds: choice("Open kinds", openKindValues, filters.get("open_kinds")),
      open_kinds_set: choice("Exact open kinds", Array.from(new Set(worlds.map(openKindsSet).filter(Boolean))).sort(),
        filters.get("open_kinds_set"), openKindsLabel),
      wave: choice("Release group", Array.from(new Set(worlds.map(function (world) {
        return world.wave == null ? null : String(world.wave);
      }).filter(Boolean))).sort(), filters.get("wave")),
      status: choice("Status", ["design", "exported"], filters.get("status")),
      kind: choice("Tower or open kind", A2.KINDS6, filters.get("kind")) };
    var advanced = A2.el("details", { class: "w2-advanced" }, [A2.el("summary", { text: "More tag filters" })]);
    advanced.appendChild(controls.kind);
    if (filters.get("kind")) advanced.open = true;
    A2.worlds.fields.forEach(function (field) {
      if (field === "open_kinds") return;
      var values = worlds.flatMap(function (world) {
        var value = A2.worlds.tagField(world, field);
        if (field === "modalities") value = modalities(world);
        return Array.isArray(value) ? value : value == null ? [] : [A2.worlds.tagValue(value)];
      });
      if (!values.length) return;
      controls[field] = choice(field.replace(/_/g, " "), Array.from(new Set(values)).sort(), filters.get(field));
      advanced.appendChild(controls[field]);
      if (filters.get(field)) advanced.open = true;
    });
    var tagValues = worlds.flatMap(function (world) {
      var value = A2.worlds.tagField(world, "tags");
      return Array.isArray(value) ? value : [];
    });
    if (tagValues.length) {
      controls.tags = choice("Tags", Array.from(new Set(tagValues)).sort(), filters.get("tags"));
      advanced.appendChild(controls.tags);
      if (filters.get("tags")) advanced.open = true;
    }
    Object.keys(controls).slice(0, 5).forEach(function (key) { bar.appendChild(controls[key]); });
    bar.appendChild(advanced);
    var summary = node("p", "", "w2-summary");
    var countStatus = A2.el("p", { role: "status", class: "a2-visually-hidden" });
    var cards = A2.el("div", { class: "w2-grid" });
    var more = A2.el("button", { type: "button", class: "w2-more" });
    var tools = A2.el("div", { class: "w2-catalog-tools" }, [bar,
      node("p", "Open kinds are the kinds you may invent. Tower or open kind also matches recorded definitions.", "w2-muted"), summary, countStatus]);
    mount.replaceChildren(cards, more);
    if (worlds[0] && worlds[0].bridgeNotice) mount.appendChild(node("p", worlds[0].bridgeNotice, "w2-muted"));
    mount.parentElement.insertBefore(tools, mount.parentElement.querySelector(".w2-contrast") || mount);
    var expanded = false;
    function draw(announce) {
      var params = new URLSearchParams();
      Object.keys(controls).forEach(function (key) { if (controls[key].value) params.set(key, controls[key].value); });
      root.history.replaceState(null, "", root.location.pathname + (params.size ? "?" + params : "") + root.location.hash);
      var matches = filterWorlds(worlds, Object.fromEntries(params));
      var visible = visibleWorlds(matches, Object.fromEntries(params), expanded);
      var exported = worlds.filter(function (world) { return A2.worlds.status(world) === "exported"; }).length;
      summary.replaceChildren(document.createTextNode(worlds.length + " world designs; " + exported +
        " have historical exports. Current core runs on this site: "),
        A2.el("a", { href: path(mount, "assets/data/atoms2/first_tower.json"), text: "Integer tower" }),
        document.createTextNode(" (Home and Learn), "),
        A2.el("a", { href: path(mount, "assets/data/atoms2/grammar_core.json"), text: "Grammar" }),
        document.createTextNode(" (Learn / Six Kinds), and "),
        A2.el("a", { href: path(mount, "assets/data/atoms2/roads_core.json"), text: "Roads" }),
        document.createTextNode(" (Home, Learn and Roads world). Other worlds have no current core run shown here. " +
          visible.length + " shown of " + matches.length + " matching."));
      if (announce) countStatus.textContent = visible.length + " worlds shown, " + matches.length + " matching.";
      cards.replaceChildren();
      visible.forEach(function (world) {
        var card = A2.el("article", { class: "w2-card" });
        var heading = A2.el("div", { class: "w2-card-heading" });
        heading.appendChild(A2.el("h2", {}, [A2.el("a", { href: path(mount, "worlds/" + world.world + "/"), text: A2.worlds.ascii(displayTitle(world)) })]));
        heading.appendChild(node("span", "RELEASE GROUP " + world.wave, "w2-eyebrow"));
        card.appendChild(heading);
        card.appendChild(node("p", PITCH[world.world] || world.title || world.world, "w2-intro"));
        card.appendChild(openKindsBadge(world));
        var first = (world.story || [])[0];
        var star = A2.worlds.tagField(world, "star_kind") || (first && first.kind) || (world.design && world.design.tower && world.design.tower[0].kind);
        var starLine = A2.el("div", { class: "w2-star" });
        starLine.appendChild(node("span", A2.worlds.tagField(world, "star_kind") ? "Featured kind:" : "First kind:"));
        if (star) starLine.appendChild(node("span", star, "w2-kind-name"));
        else starLine.appendChild(node("span", "pending"));
        card.appendChild(starLine);
        cardTags(world, star).forEach(function (part) { card.appendChild(part); });
        var strip = A2.el("div", { class: "w2-story", "aria-label": "Tower kinds in order" });
        (world.story || []).forEach(function (entry) {
          strip.appendChild(A2.token(entry.kind === "template" || root.N3 && root.N3.name(entry.name, world.world) ? entry.name :
            A2.worlds.displayIdentifier(entry), { kind: entry.kind,
            origin: "invented", layer: entry.def_layer, world: world.world }));
        });
        if (!world.story || !world.story.length) strip.appendChild(node("span", "Design tower only"));
        var towerList = A2.el("details", { class: "w2-card-tower" }, [A2.el("summary", { text: "Tower definitions" }), strip]);
        card.appendChild(towerList);
        var footer = A2.el("div", { class: "w2-card-footer" });
        if (A2.worlds.status(world) === "exported") {
          if (!(world.story || []).some(function (entry) { return A2.hasRecordedScope(entry.evidence); }))
            footer.appendChild(node("span", "scope not recorded", "w2-card-pending"));
          footer.appendChild(A2.el("a", { href: path(mount, "assets/data/worlds_v2/" + world.world + ".json"),
            text: "Historical export" }));
        } else if (world.story && world.story.some(function (entry) { return entry.evidence; }))
          footer.appendChild(node("span", "scope not recorded", "w2-card-pending"));
        else footer.appendChild(node("span", "Designed example", "w2-card-status"));
        if (!A2.worlds.hasTags(world)) {
          footer.appendChild(node("span", "tags pending", "w2-card-pending"));
        }
        footer.appendChild(A2.el("a", { href: path(mount, "worlds/" + world.world + "/"), class: "w2-link", text: "Explore world" }));
        card.appendChild(footer);
        cards.appendChild(card);
      });
      if (!matches.length) cards.appendChild(node("p", "No matching worlds. Try clearing a filter."));
      more.hidden = visible.length === matches.length;
      more.textContent = "Show all " + matches.length + " worlds";
    }
    more.addEventListener("click", function () {
      expandWorlds(cards, function () { expanded = true; draw(true); });
    });
    Object.keys(controls).forEach(function (key) { controls[key].addEventListener(key === "q" ? "input" : "change", function () {
      expanded = false; draw(true);
    }); });
    draw();
  }
  function contract(mount, world) {
    var A2 = root.A2, decl = world.decl;
    var section = A2.el("section", { class: "w2-section", "aria-label": "Layer 0 contract" });
    section.appendChild(node("h2", "Layer-0 givens"));
    if (!decl) {
      section.appendChild(node("p", "No exported declaration yet. The computer design is not an executable world."));
      return section;
    }
    if (!A2.worlds.openKinds(world)) section.appendChild(node("p", "The export does not specify open_kinds. No open-kind policy is inferred from tower entries.", "w2-muted"));
    section.appendChild(A2.worlds.fieldChips(world));
    var grid = A2.el("div", { class: "w2-contract-grid" });
    var sections = [
      ["object", decl.objects || [], "name", "doc"],
      ["operation", decl.operations || [], "name", "rule"],
      ["combinator", (decl.combinators && decl.combinators.library || []).map(function (item) {
        return typeof item === "string" ? { name: item } : { name: item && item.name };
      }), "name"],
      ["observation", decl.observation && decl.observation.probes || [], "name", "sort"],
      ["law", decl.laws || [], "name"], ["bridge", decl.bridges || [], "name"]
    ];
    sections.forEach(function (group) {
      var kind = group[0], box = A2.el("div", { class: "w2-contract-cell a2-k-" + kind });
      box.appendChild(node("h3", kind.toUpperCase() + " / " + group[1].length));
      if (!group[1].length) box.appendChild(node("p", "Not declared in this export.", "w2-muted"));
      group[1].forEach(function (item) {
        var row = A2.el("div", { class: "w2-contract-entry" });
        row.appendChild(A2.token(kind === "object" && !(root.N3 && root.N3.name(item.name, world.world, "object")) ?
          A2.worlds.displayIdentifier(Object.assign({ kind: kind }, item)) : kind === "object" ? item.name : item[group[2]],
          { kind: kind, origin: "given", world: world.world }));
        if (group[3] && item[group[3]]) row.appendChild(node("small", A2.worlds.ascii(item[group[3]])));
        box.appendChild(row);
      });
      grid.appendChild(box);
    });
    section.appendChild(grid);
    section.appendChild(node("p", "Judge view: " + (decl.observation && decl.observation.judge_view || "not recorded") +
      ". Unlisted observations are not a learner capability.", "w2-foot"));
    return section;
  }
  function designBadge(world, subject, href) {
    return root.A2.badge("design", { record: {
      method: "not run",
      scope: { domain: world, description: subject + ". Proposed in the depth design; no verification run is recorded." },
      artifact: { file: "Design record: " + world + " world, depth pass (11-04)", href: href,
        schema: "opulse.worlds_ui_design/1" }
    } });
  }
  function designName(row, world) {
    var name = row.name;
    var validDisplay = root.N3 && typeof name === "string" && Array.from(name).some(function (character) {
      return root.N3.ALLOWED.has(character);
    });
    if (validDisplay) {
      try { validDisplay = root.N3.toDisplay(root.N3.toAscii(name)) === name; }
      catch (error) { validDisplay = false; }
    }
    return typeof name === "string" && name.trim() && (/^[\x20-\x7e]+$/.test(name) || validDisplay) ?
      root.A2.token(name, { kind: row.kind, layer: row.layer, world: world }) :
      node("span", "Design identifier pending in ASCII");
  }
  function fixtureNotice(id, world) {
    if (id === "action") {
      var example = world && world.story && world.story[0] && world.story[0].examples[0];
      return example && example.judge_view && Array.isArray(example.judge_view.map) ?
        "The historical corridor case includes a judge-only map in its download. The proposed maze grants learners front probes only." :
        "The proposed maze grants learners front probes only; its map is not published in this export.";
    }
    if (id === "pixels") return world && world.decl && (world.decl.objects || []).some(function (item) { return item.name === "A0"; }) ?
      "Grid A0 has published cells in the layer-0 declaration. The growth task below is a separate design." :
      "Grid A0 cells are not published in this export. The growth task below is a separate design.";
    return null;
  }
  function publishedFixture(world) {
    var A2 = root.A2;
    if (world.world === "action") {
      var example = world.story && world.story[0] && world.story[0].examples[0];
      var map = example && example.judge_view && example.judge_view.map;
      if (Array.isArray(map)) return A2.el("details", { class: "w2-fixture" }, [
        node("summary", "Inspect the judge-only map in the download (not available to the learner)"),
        A2.el("pre", { text: map.join("\n") })]);
    }
    if (world.world === "pixels") {
      var grid = (world.layer0 && world.layer0.objects || []).find(function (item) {
        return typeof (item.decl || item.ascii) === "string" && (item.decl || item.ascii).startsWith("obj A0 =");
      });
      if (grid) return A2.el("details", { class: "w2-fixture" }, [
        node("summary", "Inspect the published Grid A0 declaration"), A2.expr(grid.decl || grid.ascii, { world: world.world })]);
    }
    return null;
  }
  function bridgePanel(mount, world) {
    var bridges = (world.bridges || []).filter(function (bridge) {
      return [bridge.source_world, bridge.target_world].some(function (name) {
        return name && name.split("@")[0] === world.world;
      });
    });
    if (!bridges.length) return null;
    var section = root.A2.el("section", { class: "w2-section" });
    section.appendChild(node("h2", "Cross-world bridges"));
    section.appendChild(node("p", "Bridge records come from the separate bridges export. Their recorded checks are not rerun here.", "w2-muted"));
    bridges.forEach(function (bridge) {
      var item = root.A2.el("article", { class: "w2-bridge" });
      item.appendChild(root.A2.el("h3", {}, [root.A2.token("~" + bridge.name, { kind: "bridge", origin: "invented", world: world.world })]));
      item.appendChild(root.A2.badge("design", { record: {
        artifact: { file: "bridges.json", href: path(mount, "assets/data/worlds_v2/bridges/bridges.json") },
        evidence: bridge.evidence
      } }));
      var mismatches = bridgeVersionMismatch(bridge, world.worldExports);
      if (mismatches.length) {
        item.appendChild(node("p", "evidence for an earlier world version", "w2-eyebrow"));
        item.appendChild(root.A2.el("ul", { class: "w2-version-note" }, mismatches.map(function (difference) {
          return root.A2.el("li", {}, [node("strong", difference.world + ": "),
            node("span", "evidence hash "), root.A2.el("code", { text: difference.evidence }),
            node("span", "; published export hash "), root.A2.el("code", { text: difference.published })]);
        })));
      }
      var introduction = root.A2.el("p", { class: "w2-intro" });
      introduction.appendChild(node("span", root.A2.worlds.ascii(bridge.source_world) + " to " +
        root.A2.worlds.ascii(bridge.target_world) + ". "));
      introduction.appendChild(proseNode("span", bridge.definition, world.world));
      item.appendChild(introduction);
      if (bridge.decl) {
        var sourceStatus = world.parseStatus && world.parseStatus.entries["bridge/" + bridge.name];
        var isDesign = root.N3 && typeof root.N3.isDesign === "function" && root.N3.isDesign(bridge.decl, world.world);
        var notation = !isDesign && root.N3 && root.N3.lookup(bridge.decl, world.world);
        if (!isDesign && (notation || sourceStatus === true)) {
          item.appendChild(node("p", notation ? "Definition" : "ASCII source", "w2-eyebrow"));
          if (notation && notation.signature) item.appendChild(root.A2.expr(notation.signature.display, { world: world.world }));
          item.appendChild(root.A2.expr(bridge.decl, { world: world.world }));
        } else {
          item.appendChild(node("p", sourceStatus === "placeholder (core notation cannot encode this body)" ?
            sourceStatus : "Design text (not notation v3 source)", "w2-eyebrow"));
          item.appendChild(root.A2.expr(bridge.decl, { world: world.world, design: true }));
        }
      }
      if (bridge.examples && bridge.examples.length) {
        var example = bridge.examples[0];
        item.appendChild(node("p", "Recorded example", "w2-eyebrow"));
        if (example.text) {
          if (root.N3 && typeof root.N3.isDesign === "function" && root.N3.isDesign(example.text, world.world))
            item.appendChild(node("p", "Design text (not notation v3)", "w2-eyebrow"));
          item.appendChild(root.A2.expr(example.text, { world: world.world }));
        }
        if (example.outcome) item.appendChild(typeof example.outcome === "string" ?
          root.A2.expr(example.outcome, { world: world.world }) : root.A2.value(example.outcome, { world: world.world }));
      }
      item.appendChild(root.A2.el("a", { href: path(mount, "assets/data/worlds_v2/bridges/bridges.json"),
        text: "Inspect bridge evidence and scope" }));
      section.appendChild(item);
    });
    return section;
  }
  function designTower(container, rows, world, href, parseStatus) {
    var A2 = root.A2, selector = A2.el("div", { class: "w2-rail", role: "group", "aria-label": "Select a designed layer" });
    var detailPanel = A2.el("div", { class: "w2-display" });
    var layerStatus = A2.el("p", { role: "status", class: "a2-visually-hidden" });
    function choose(index, announce) {
      selector.querySelectorAll("button").forEach(function (button, position) {
        button.setAttribute("aria-pressed", String(index === position));
      });
      var row = rows[index], card = A2.el("article", { class: "w2-step a2-k-" + row.kind });
      card.appendChild(node("p", "DESIGN LAYER " + row.layer, "w2-eyebrow"));
      card.appendChild(A2.el("h3", {}, [designName(row, world)]));
      card.appendChild(designBadge(String(world).replace(/^design:/, ""), "Tower layer " + row.layer + ": " + row.name, href));
      if (typeof row.decl === "string" && row.decl) {
        var sourceStatus = parseStatus && parseStatus.entries["design/" + String(world).replace(/^design:/, "") + "/" + row.name];
        var isDesign = root.N3 && typeof root.N3.isDesign === "function" && root.N3.isDesign(row.decl, world);
        var notation = !isDesign && root.N3 && root.N3.lookup(row.decl, world);
        if (!isDesign && (notation || sourceStatus === true)) {
          card.appendChild(node("p", notation ? "Definition" : "ASCII source", "w2-eyebrow"));
          if (notation && notation.signature) card.appendChild(A2.expr(notation.signature.display, { world: world }));
          card.appendChild(A2.expr(row.decl, { world: world }));
        } else {
          card.appendChild(node("p", sourceStatus === "placeholder (core notation cannot encode this body)" ?
            sourceStatus : "Design text (not notation v3 source)", "w2-eyebrow"));
          card.appendChild(root.N3 ? A2.expr(row.decl, { world: world, design: true }) :
            node("p", row.decl, "w2-design-text"));
        }
      }
      if (row.example != null) {
        card.appendChild(node("p", "Designed example and proposed result", "w2-eyebrow"));
        // Design records (worlds/designs.json) show converted formulas when a block has them;
        // other design strings are labelled plain text, never machine notation posing as v3.
        var designed = function (text) {
          return !(root.N3 && root.N3.lookup(text, world));
        };
        if (designed(row.example)) card.appendChild(node("p", "Design text (not notation v3)", "w2-eyebrow"));
        card.appendChild(A2.expr(row.example, { world: world, design: designed(row.example) }));
        if (row.value != null) card.append(node("span", "  ->  ", "w2-arrow"),
          typeof row.value === "string" ? A2.expr(row.value, { world: world, design: designed(row.value) }) :
            A2.value(row.value, { world: world }));
      }
      detailPanel.replaceChildren(card);
      if (announce) layerStatus.textContent = "Selected layer " + row.layer + ": " + row.name + ".";
    }
    rows.forEach(function (row, index) {
      var button = A2.el("button", { type: "button", class: "w2-rail-button", "aria-pressed": "false" }, [
        node("small", "L" + row.layer), designName(row, world)]);
      button.addEventListener("click", function () { choose(index, true); });
      selector.appendChild(button);
    });
    selector.addEventListener("keydown", function (event) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      var buttons = Array.from(selector.querySelectorAll("button"));
      var index = buttons.indexOf(root.document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      var next = buttons[(index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length];
      next.focus(); next.click();
    });
    container.append(selector, layerStatus, detailPanel);
    choose(rows.length - 1);
    if (root.requestAnimationFrame) root.requestAnimationFrame(function () {
      var selected = selector.querySelector('button[aria-pressed="true"]');
      selector.scrollLeft = selected.offsetLeft - selector.offsetLeft - (selector.clientWidth - selected.offsetWidth) / 2;
    });
  }
  function detail(mount, world) {
    if (root.N3) root.N3.register(world.notation3);
    var A2 = root.A2, id = world.world, source = mount.dataset.root + "assets/data/worlds_v2/" + id + ".json";
    var designSource = mount.dataset.root + "worlds/designs.json";
    var placeholderHeading = mount.parentElement && mount.parentElement.querySelector(":scope > h1");
    if (placeholderHeading && placeholderHeading.tagName === "H1") placeholderHeading.remove();
    var intro = A2.el("header", { class: "w2-hero" });
    intro.appendChild(A2.el("a", { href: path(mount, "worlds/"), class: "w2-back", text: "Worlds / Catalog" }));
    intro.appendChild(node("p", "WORLD " + id.toUpperCase() + " / RELEASE GROUP " + world.wave, "w2-eyebrow"));
    intro.appendChild(node("h1", A2.worlds.ascii(displayTitle(world))));
    if (world.design) intro.appendChild(designBadge(id, "World design", designSource));
    intro.appendChild(openKindsBadge(world));
    intro.appendChild(node("p", id === "roads" ?
      "The Metro cases below run through the current core. Older exported outcomes and design text are shown separately." :
      world.design ? "This page combines a world design with earlier exported outcomes. The export has not been checked against the current core. Inspect a case for its recorded scope; no design challenge here is a verified v2 result." :
        "This historical export has not been checked against the current core. Inspect a case for its recorded scope.", "w2-muted"));
    if (id === "roads") intro.appendChild(node("p", "See the current-core panel for the artifact's weighted topology and check scope. Metro runs are separate calls outside that checked scope.", "w2-muted"));
    intro.appendChild(node("p", PITCH[id] || world.title || id, "w2-lead"));
    var playCase = ["integer", "computer", "roads"].includes(id);
    var actionLink = id === "roads" ? path(mount, "play/challenge/") : id === "integer" ?
      path(mount, "play/?world=integer") + "#definition-workshop" : id === "computer" ?
      path(mount, "play/?world=computer") : "#select-an-exported-tower-row";
    var actionText = id === "roads" ? "Try the 277-closure route challenge" : id === "integer" ?
      "Open the integer definition workshop" : id === "computer" ? "Open the separate browser preview" : "Inspect exported cases";
    var parsed = (world.story || []).filter(function (row) {
      return world.parseStatus && world.parseStatus.entries[world.world + "/" + row.name] === true;
    }).length;
    if (world.parseStatus) {
      var parseNote = A2.el("div", { class: "w2-parse-note" });
      var placeholders = (world.story || []).filter(function (row) {
        return world.parseStatus.entries[world.world + "/" + row.name] === "placeholder (core notation cannot encode this body)";
      }).length;
      parseNote.appendChild(node("p", "Core parser: " + parsed + " of " + (world.story || []).length +
        " design declarations parse as ASCII source" + "; " + placeholders + " parse but are placeholders"));
      parseNote.appendChild(A2.el("p", {}, ["These design records are not current-core runs. See ",
        A2.el("a", { href: path(mount, "learn/checks/#world-export-limitations"), text: "world export limitations" }), "."]));
      intro.appendChild(parseNote);
    }
    var actions = A2.el("nav", { class: "w2-actions", "aria-label": "Next action" }, [
      A2.el("a", { href: actionLink, text: actionText })]);
    if (!playCase) actions.appendChild(A2.el("a", { href: path(mount, "build/world/"), text: "Create a world like this" }));
    intro.appendChild(actions);
    var main = A2.el("div", { class: "w2-detail" });
    main.appendChild(intro);
    if (world.bridgeNotice) main.appendChild(node("p", world.bridgeNotice, "w2-muted"));
    if (id === "roads") {
      var exported = A2.el("section", { class: "w2-spotlight" });
      exported.appendChild(node("p", "RECORDED METRO CUT CERTIFICATE / DIFFERENT QUESTION", "w2-eyebrow"));
      exported.appendChild(node("h2", "Recorded Metro cut outcome"));
      exported.appendChild(node("p", "The historical export below is separate from the current-core Metro runs that follow.", "w2-intro"));
      var last = world.story[world.story.length - 1];
      var sample = last.examples[0];
      var graph = sample.inputs[0];
      var junctions = graph && graph.f && graph.f[0] && graph.f[0].f;
      var roads = graph && graph.f && graph.f[1] && graph.f[1].f;
      exported.appendChild(A2.worlds.exportNotation(sample) ?
        A2.expr(A2.worlds.exportNotation(sample), { given: A2.worlds.givenNames(world.decl), world: world.world }) :
        A2.token(A2.worlds.identifier(last), { kind: last.kind, layer: last.def_layer, world: world.world }));
      exported.appendChild(node("p", "Recorded outcome", "w2-eyebrow"));
      exported.appendChild(A2.worlds.recordedValue("outcome", sample.outcome,
        A2.worlds.givenNames(world.decl), false, world.world));
      exported.appendChild(node("p", "Recorded scope: " + A2.worlds.scope(last) + ".", "w2-foot"));
      var inputs = A2.el("div", { class: "w2-inputs" }, [node("span", "Inputs:", "w2-eyebrow")]);
      sample.inputs.forEach(function (input) {
        inputs.appendChild(A2.worlds.recordedValue("input", input, A2.worlds.givenNames(world.decl), false, world.world));
      });
      exported.appendChild(typeof matchMedia === "function" && matchMedia("(max-width: 600px)").matches ?
        A2.el("details", { class: "w2-long-value" }, [node("summary", "Inspect recorded inputs"), inputs]) : inputs);
      exported.appendChild(node("p", "The export records the cut-certificate observation on a graph with " +
        (junctions ? junctions.length : "unrecorded") + " junctions and " + (roads ? roads.length : "unrecorded") +
        " roads, from " + A2.worlds.safeValueNotation(sample.inputs[1]) + " to " +
        A2.worlds.safeValueNotation(sample.inputs[2]) + ". This historical outcome is not the current-core run below.", "w2-intro"));
      exported.appendChild(A2.worlds.towerBadge(last, source, world.decl));
      var spotlight = A2.el("section", { class: "w2-spotlight" });
      spotlight.appendChild(node("p", "CURRENT CORE / METRO RUNS", "w2-eyebrow"));
      spotlight.appendChild(node("h2", "Routes, closures and a cut"));
      var coreUrl = path(mount, "assets/data/atoms2/roads_core.json");
      var coreContent = node("p", "Loading promoted roads records...", "w2-muted");
      spotlight.appendChild(coreContent);
      fetch(coreUrl).then(function (response) {
        if (!response.ok) throw new Error("Roads core artifact unavailable");
        return response.json();
      }).then(function (core) {
        if (root.N3) root.N3.register(core.notation3);
        coreContent.replaceChildren();
        coreContent.appendChild(A2.el("a", { href: coreUrl, text: "Open versioned core run artifact" }));
        var list = A2.el("ol");
        ["cost", "best", "optimal", "survives", "mincut", "cut_certificate"].forEach(function (name) {
          var card = core.cards.find(function (entry) { return entry.name === name; });
          var outcome = card.example.outcome;
          var item = A2.el("li");
          item.appendChild(A2.expr(card.example.call, { world: world.world }));
          item.appendChild(A2.runBadge(card.example, coreUrl));
          item.appendChild(document.createTextNode(" = "));
          item.appendChild(A2.value(outcome, { world: world.world }));
          item.appendChild(node("span", "; " + card.example.steps + " layer-0 steps. " +
            (!A2.hasRecordedScope(card.evidence) ? "Core run on Metro (scope not recorded). " :
              card.example.outside_checked_scope ? "Core run on Metro (outside the checked scope). " : "Core run on Metro. ")));
          list.appendChild(item);
        });
        coreContent.appendChild(list);
        var definitions = A2.el("div", { class: "w2-foot" }, [node("strong", "Definition evidence: ")]);
        ["Route", "cost", "best", "optimal", "survives", "cut_certificate"].forEach(function (name) {
          var card = core.cards.find(function (entry) { return entry.name === name; });
          definitions.appendChild(A2.expr(card.display_name, { world: world.world }));
          definitions.appendChild(A2.scopedBadge(card.evidence, null,
            { file: "docs/assets/data/atoms2/roads_core.json", href: coreUrl }));
          definitions.appendChild(document.createTextNode(" "));
        });
        coreContent.appendChild(definitions);
        coreContent.appendChild(A2.el("p", {}, [A2.expr(core.failing.call, { world: world.world }),
          A2.runBadge(core.failing, coreUrl), document.createTextNode(" = "),
          root.N3 && root.N3.value(core.failing.outcome, world.world) ?
            A2.value(core.failing.outcome, { world: world.world }) : node("span", A2.formatValue(core.failing.outcome)),
          node("span", ". " +
            (core.failing.outside_checked_scope ? "Core run on Metro (outside the checked scope). " : "Core run on Metro. ")),
          ]));
        coreContent.appendChild(node("p", "Metro has 12 junctions and 23 roads. The core finds Edges<AB,AC,AD> as a minimum cut and ?cut_certificate{Metro,A,L} returns true. The 277 closures of size at most two are a Metro run, outside the recorded checked scope.", "w2-foot"));
      }).catch(function () { coreContent.textContent = "Core run artifact unavailable. Reload to try again."; });
      main.appendChild(spotlight);
      main.appendChild(exported);
    }
    var section = A2.el("section", { class: "w2-section" });
    section.id = "select-an-exported-tower-row";
    section.appendChild(node("h2", "Select an exported tower row"));
    section.appendChild(node("p", "How to read this page: Select an exported row to see its recorded cases. Its row number is the story order; L is the computed dependency depth. The separate design record proposes harder cases. Use the arrow keys to change rows.", "w2-muted"));
    var tower = A2.el("div");
    A2.worlds.tower(tower, world, source);
    section.appendChild(tower);
    var bridges = bridgePanel(mount, world);
    if (world.design && world.design.tower) {
      section.appendChild(node("h3", "Twelve-layer design record"));
      section.appendChild(node("p", "Select a designed layer to inspect its proposed declaration and example.", "w2-muted"));
      // Design towers have their own legend world ('design:<world>'), apart from the export's.
      var designWorld = root.N3 && root.N3.legend("design:" + id).length ? "design:" + id : id;
      designTower(section, world.design.tower, designWorld, designSource, world.parseStatus);
    }
    main.appendChild(section);
    if (bridges) main.appendChild(bridges);
    var contractPanel = A2.el("details", { class: "w2-contract-panel" });
    contractPanel.appendChild(node("summary", "Inspect layer-0 givens"));
    contractPanel.appendChild(contract(mount, world));
    main.appendChild(contractPanel);
    if (SCOPE[id]) {
      var ladder = A2.el("section", { class: "w2-section" });
      ladder.appendChild(node("h2", "03 / Five levels of difficulty"));
      if (id !== "roads") ladder.appendChild(designBadge(id, "Five-level difficulty ladder", designSource));
      ladder.appendChild(node("p", id === "roads" ?
        "These five scopes are designs. Recorded Metro calls are shown separately above." :
        "The design record proposes these harder cases.", "w2-muted"));
      var steps = A2.el("ol", { class: "w2-ladder" });
      SCOPE[id].forEach(function (item, index) {
        steps.appendChild(A2.el("li", {}, [node("strong", "LEVEL " + (index + 1)), node("span", item),
          designBadge(id, "Difficulty level " + (index + 1), designSource)]));
      });
      ladder.appendChild(steps);
      main.appendChild(ladder);
    }
    var showcase = A2.el("section", { class: "w2-section w2-showcase" });
    var hasShowcase = Array.isArray(world.showcase) && world.showcase.length > 0;
    var emptyShowcase = !hasShowcase;
    showcase.appendChild(node("h2", world.design ? "04 / Designed showcase and historical exports" :
      emptyShowcase ? "No published showcase" : "Historical exports"));
    if (emptyShowcase) showcase.appendChild(A2.el("p", {}, [
      "No published showcase for this world. ", A2.el("a", { href: source, text: "Inspect the world export" })]));
    if (fixtureNotice(id, world)) showcase.appendChild(node("p", fixtureNotice(id, world), "w2-muted"));
    var fixture = publishedFixture(world);
    if (fixture) showcase.appendChild(fixture);
    if (hasShowcase) publishedShowcases(showcase, world, source);
    if (id !== "roads" && world.design && world.design.prompt) {
      showcase.appendChild(node("h3", "Separate proposed task"));
      showcase.appendChild(designBadge(id, "Designed showcase", designSource));
      showcase.appendChild(designBrief(world.design, id));
      var proposed = recordedAnswer(world.design);
      if (proposed) {
        showcase.appendChild(node("p", "Proposed answer", "w2-eyebrow"));
        showcase.appendChild(typeof proposed.value === "string" ?
          (root.N3 && root.N3.lookup(proposed.value, id) ? A2.expr(proposed.value, { world: id }) :
            proseNode("p", proposed.value, id)) : A2.value(proposed.value, { world: id }));
      }
    }
    if (id === "roads") showcase.appendChild(node("p", "The Metro cut and certificate are core-run cases in the panel above. This section only contains older exports.", "w2-foot"));
    if (world.design) showcase.appendChild(node("p", "Design modalities: " + ((world.design.modalities || []).join(", ") || "not recorded") + ". Text carries the same question as any optional image or audio rendering.", "w2-foot"));
    main.appendChild(showcase);
    main.appendChild(A2.el("nav", { class: "w2-actions" }, [
      ...(playCase ? [A2.el("a", { href: actionLink, text: actionText })] : []),
      A2.el("a", { href: path(mount, "build/world/"), text: "Create a world like this" })]));
    mount.replaceChildren(main);
  }
  function load(mount) {
    var A2 = root.A2;
    if (!A2 || !A2.worlds) return;
    var id = mount.dataset.world;
    var base = path(mount, "assets/data/worlds_v2/");
    fetch(base + "index.json").then(function (response) { if (!response.ok) throw Error("Index unavailable"); return response.json(); })
      .then(function (index) {
        if (index.schema !== "opulse.world_v2_index/1") throw Error("Unexpected index schema");
        return Promise.all(index.worlds.map(function (entry) {
          return fetch(base + entry.file).then(function (response) { if (!response.ok) throw Error(entry.file + " unavailable"); return response.json(); })
            .then(function (exported) {
              if (exported.schema !== "opulse.world_v2_export/1" || exported.world !== entry.world) throw Error("Unexpected export: " + entry.world);
              return Object.assign({}, exported, { title: entry.title, wave: entry.wave,
                tags: entry.tags || exported.tags });
            });
        })).then(function (worlds) { return Promise.all([worlds, fetch(base + "computer.json")
          .then(function (response) { if (!response.ok) throw Error("computer.json unavailable"); return response.json(); })
          .then(function (computer) {
            if (computer.schema !== "opulse.world_v2_export/1" || computer.world !== "computer") throw Error("Unexpected computer export");
            return Object.assign({}, computer, { title: "Finite computer", wave: 2 });
          }), fetch(path(mount, "worlds/designs.json"))
          .then(function (response) { if (!response.ok) throw Error("Design bundle unavailable"); return response.json(); }),
          loadBridges(index, base, fetch), fetch(path(mount, "assets/data/atoms2/parse_status.json"))
            .then(function (response) { if (!response.ok) throw Error("Parse status unavailable"); return response.json(); })]); });
      }).then(function (worlds) {
        var exports = worlds[0], computer = worlds[1], designBundle = worlds[2], bridges = worlds[3], parseStatus = worlds[4];
        if (designBundle.schema !== "opulse.worlds_ui_design/1") throw Error("Unexpected design schema");
        if (parseStatus.schema !== "opulse.atoms2_parse_status/1") throw Error("Unexpected parse status schema");
        if (!exports.some(function (entry) { return entry.world === "computer"; })) exports.push(computer);
        if (root.N3) exports.forEach(function (entry) { root.N3.register(entry.notation3); });
        var worldHashes = Object.fromEntries(exports.map(function (entry) { return [entry.world, entry.world_hash]; }));
        if (root.N3) root.N3.register(designBundle.notation3);
        exports.forEach(function (entry) {
          entry.worldExports = worldHashes;
          entry.parseStatus = parseStatus;
          entry.design = designBundle.worlds[entry.world];
          entry.bridges = (entry.bridges || []).concat(bridges.story);
          entry.bridgeNotice = entry.bridges.length ? "" : bridgeNotice(bridges);
        });
        var world = exports.find(function (item) { return item.world === id; });
        if (id && !world) throw Error("World not found: " + id);
        if (id) detail(mount, world); else catalog(mount, exports);
      }).catch(function () {
        mount.replaceChildren(node("p", "World exports could not be loaded. Check the site data bundle and reload."));
      });
  }
  function start() {
    root.document.querySelectorAll("[data-worlds-v2]:not([data-ready])").forEach(function (mount) {
      mount.dataset.ready = "1";
      load(mount);
    });
  }
  if (typeof root.document !== "undefined") {
    if (root.document.readyState === "loading") root.document.addEventListener("DOMContentLoaded", start);
    else start();
    if (root.document$ && root.document$.subscribe) root.document$.subscribe(start);
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { filterWorlds: filterWorlds, openKindsSet: openKindsSet, openKindsLabel: openKindsLabel, visibleWorlds: visibleWorlds, expandWorlds: expandWorlds, modalities: modalities, scope: SCOPE, pitch: PITCH, designBadge: designBadge, designName: designName, designTower: designTower, fixtureNotice: fixtureNotice, bridgePanel: bridgePanel, bridgeVersionMismatch: bridgeVersionMismatch, publishedFixture: publishedFixture, loadBridges: loadBridges, bridgeNotice: bridgeNotice, showcaseEntry: showcaseEntry, publishedShowcases: publishedShowcases, recordedAnswer: recordedAnswer, displayTitle: displayTitle, designBrief: designBrief, cardTags: cardTags, openKindsBadge: openKindsBadge, contract: contract };
})(typeof window !== "undefined" ? window : globalThis);
