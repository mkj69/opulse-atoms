(function (root) {
  "use strict";

  var ANGLES = ["compute", "invert", "decide", "describe", "induce", "create"];
  var DATA_URL = "../../assets/data/challenge/v2.json";

  function equal(left, right) {
    if (left === right) return true;
    if (Array.isArray(left) && Array.isArray(right)) {
      return left.length === right.length && left.every(function (item, index) { return equal(item, right[index]); });
    }
    if (!left || !right || typeof left !== "object" || typeof right !== "object" ||
        Array.isArray(left) || Array.isArray(right)) return false;
    var keys = Object.keys(left);
    return keys.length === Object.keys(right).length && keys.every(function (key) {
      return Object.prototype.hasOwnProperty.call(right, key) && equal(left[key], right[key]);
    });
  }

  function validValue(value) {
    if (!value || typeof value !== "object" || Array.isArray(value) || typeof value.t !== "string") return false;
    if (value.t === "int") return Object.keys(value).length === 2 && Number.isSafeInteger(value.v);
    if (value.t === "str") return Object.keys(value).length === 2 && typeof value.v === "string";
    return Object.keys(value).length === 3 && typeof value.tag === "string" && Array.isArray(value.f) &&
      value.f.every(validValue);
  }

  function outcome(answer) {
    if (!answer || typeof answer !== "object" || Array.isArray(answer) || Object.keys(answer).length !== 1) return null;
    if (Object.prototype.hasOwnProperty.call(answer, "ok") && validValue(answer.ok)) return { ok: answer.ok };
    if (typeof answer.bottom === "string") return { bottom: answer.bottom };
    return null;
  }

  function hasUnknown(value) {
    return value && typeof value === "object" &&
      (Object.prototype.hasOwnProperty.call(value, "unknown") ||
        Object.keys(value).some(function (key) { return hasUnknown(value[key]); }));
  }

  function validOfflineAnswer(task, answer) {
    if (hasUnknown(answer)) return false;
    try { canonical(answer); } catch (_error) { return false; }
    switch (task.answer_format) {
      case "value": return typeof answer === "string" && answer.length > 0 && !/^Unknown\(/.test(answer) ||
        !!outcome(answer) || !!answer && typeof answer === "object" && !Array.isArray(answer) &&
          typeof answer.true === "boolean";
      case "choice": return typeof answer === "string" && answer.length > 0;
      case "definition": return typeof answer === "string" && answer.length > 0 ||
        !!answer && typeof answer === "object";
      case "verdict": return !!answer && typeof answer === "object" && !Array.isArray(answer) &&
        typeof answer.true === "boolean";
      case "one_witness": return answer !== null;
      case "all_solutions": return Array.isArray(answer);
      default: return false;
    }
  }

  function parseAnswer(task, input, schema) {
    var text = input.trim();
    if (!text) throw new Error("Enter an answer first.");
    if (/[^\x00-\x7f]/.test(text)) throw new Error("Use ASCII notation only.");
    function checked(answer) {
      if (schema === "opulse.challenge_v2/3" && !validOfflineAnswer(task, answer)) {
        throw new Error("Invalid answer shape or unsupported number for " + task.answer_format.replace(/_/g, " ") + ".");
      }
      return answer;
    }
    if (task.answer_format === "definition" && (text.charAt(0) === "{" || text.charAt(0) === "[")) {
      try { return checked(JSON.parse(text)); } catch (error) {
        if (error instanceof SyntaxError) throw new Error("Enter valid JSON for this definition.");
        throw error;
      }
    }
    if (task.answer_format === "choice" || task.answer_format === "definition") {
      if (text.charAt(0) === '"') {
        try { return checked(JSON.parse(text)); } catch (error) {
          if (error instanceof SyntaxError) throw new Error("Enter an ASCII option or definition.");
          throw error;
        }
      }
      return checked(text);
    }
    if (task.answer_format === "value" && /^-?(0|[1-9][0-9]*)$/.test(text)) {
      var integer = Number(text);
      if (!Number.isSafeInteger(integer)) throw new Error("Use an exact safe integer or the Python grader.");
      return checked({ ok: { t: "int", v: integer } });
    }
    if (task.answer_format === "value" && (text === "true" || text === "false")) {
      return checked({ ok: { t: "bool", tag: text, f: [] } });
    }
    if (task.answer_format === "value" && /^Bottom\([A-Za-z0-9_ -]+\)$/.test(text)) {
      return checked({ bottom: text.slice(7, -1) });
    }
    try { return checked(JSON.parse(text)); } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
      if (task.answer_format === "value" && !/^[\[{\"]/.test(text)) return checked(text);
      throw new Error("Enter valid JSON for this answer format.");
    }
  }

  function canonical(value) {
    if (value === null || typeof value === "boolean" || typeof value === "string") {
      return JSON.stringify(value).replace(/[^\x00-\x7e]/g, function (character) {
        return Array.from(character).map(function (unit) {
          return "\\u" + unit.charCodeAt(0).toString(16).padStart(4, "0");
        }).join("");
      });
    }
    if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") {
      return "{" + Object.keys(value).sort(function (left, right) {
        var leftPoints = Array.from(left, function (character) { return character.codePointAt(0); });
        var rightPoints = Array.from(right, function (character) { return character.codePointAt(0); });
        for (var index = 0; index < Math.min(leftPoints.length, rightPoints.length); index++) {
          if (leftPoints[index] !== rightPoints[index]) return leftPoints[index] - rightPoints[index];
        }
        return leftPoints.length - rightPoints.length;
      }).map(function (key) {
        return canonical(key) + ":" + canonical(value[key]);
      }).join(",") + "}";
    }
    throw new TypeError("Unsupported JSON value or unsafe number");
  }

  async function answerHash(identifier, value) {
    var bytes = new TextEncoder().encode(identifier + "\u0000" + canonical(value));
    if (typeof module !== "undefined" && module.exports) {
      return require("node:crypto").createHash("sha256").update(bytes).digest("hex");
    }
    var digest = await root.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), function (byte) { return byte.toString(16).padStart(2, "0"); }).join("");
  }

  async function grade(task, answer, schema) {
    if (schema === "opulse.challenge_v2/3") {
      return { status: validOfflineAnswer(task, answer) ? "offline" : "invalid", method: "offline_exact" };
    }
    var method = task.grader.method || "exact_value";
    var shape = task.answer_format;
    if (shape === "definition") return { status: "python", method: method };
    if (!task.grader.check) return { status: "invalid", method: method };
    if ((shape === "choice" && typeof answer !== "string") ||
        (shape === "verdict" && (!answer || typeof answer !== "object" ||
          Array.isArray(answer) || typeof answer.true !== "boolean")) ||
        (shape === "value" && answer && typeof answer === "object" &&
          (Object.prototype.hasOwnProperty.call(answer, "ok") || Object.prototype.hasOwnProperty.call(answer, "bottom")) && !outcome(answer)) ||
        hasUnknown(answer)) {
      return { status: "invalid", method: method };
    }
    try {
      var check = task.grader.check;
      if (shape === "value" || shape === "choice" || shape === "verdict") {
        var exact = await answerHash(task.id, answer) === check.hash;
        return { status: exact ? "correct" : shape === "verdict" && !check.complete ? "undecidable" : "incorrect", method: method };
      }
      if (shape === "one_witness") {
        var inScope = check.scope.some(function (candidate) { return equal(candidate, answer); });
        var matched = inScope && check.hashes.includes(await answerHash(task.id, answer));
        return { status: matched ? "correct" : check.complete ? "incorrect" : "undecidable", method: method };
      }
      if (shape === "all_solutions") {
        if (!Array.isArray(answer) || answer.length !== check.hashes.length) return { status: "incorrect", method: method };
        var hashes = [];
        for (var candidate of answer) {
          if (!check.scope.some(function (item) { return equal(item, candidate); })) return { status: "incorrect", method: method };
          hashes.push(await answerHash(task.id, candidate));
        }
        var complete = new Set(hashes).size === hashes.length && equal(hashes.sort(), check.hashes);
        return { status: complete ? "correct" : "incorrect", method: method };
      }
    } catch (_error) { return { status: "invalid", method: method }; }
    return { status: "python", method: method };
  }

  function featuredRoute(data) {
    return data.paths.six_kinds_one_world;
  }

  function shellQuote(value) { return "'" + String(value).replace(/'/g, "'\\''") + "'"; }

  function pythonCommand(task, answer, schema) {
    return "PYTHONPATH=src python -m opulse.tasks_v2.challenge_grade " + shellQuote(task.id) + " " + shellQuote(JSON.stringify(answer));
  }

  function node(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function button(text, className, handler) {
    var element = node("button", className, text);
    element.type = "button";
    element.addEventListener("click", handler);
    return element;
  }

  function status(task) {
    return task.label === "legacy-v1 operations world" ? root.A2.badge("legacy") : root.A2.badge("design", { artifact: "challenge/v2.json" });
  }

  function item(task, position, select) {
    var card = node("button", "ladder-item");
    card.type = "button";
    card.dataset.taskId = task.id;
    card.addEventListener("click", function () { select(task); });
    var meta = node("span", "ladder-item-meta");
    meta.appendChild(node("span", "ladder-index", String(position + 1).padStart(2, "0")));
    meta.appendChild(node("span", "ladder-level", "LEVEL " + task.level));
    meta.appendChild(root.A2.kindBadge(task.kind));
    card.appendChild(meta);
    card.appendChild(node("strong", "ladder-item-world", task.world));
    card.appendChild(node("span", "ladder-item-purpose", task.purpose));
    card.appendChild(node("span", "ladder-item-label", task.label === "legacy-v1 operations world" ? "Legacy-v1 operations world" :
      "Designed example / atoms-v2" + (task.id.includes("/template/") ? " / template" : "")));
    return card;
  }

  function renderTask(host, task, parseStatus, schema) {
    var offline = schema === "opulse.challenge_v2/3";
    host.replaceChildren();
    var header = node("div", "ladder-detail-header");
    header.appendChild(node("span", "ladder-kicker", task.angle ? "TASK / " + task.angle.toUpperCase() : "GUIDED ROUTE / " + task.kind.toUpperCase()));
    header.appendChild(status(task));
    host.appendChild(header);
    host.appendChild(node("h2", "", task.world + (task.level === undefined ? " / " + task.name : " / level " + task.level)));
    var meta = node("div", "ladder-detail-meta");
    meta.appendChild(root.A2.kindBadge(task.kind));
    meta.appendChild(node("span", "", task.purpose));
    host.appendChild(meta);
    if (task.definition) {
      var isSource = parseStatus && parseStatus.entries[task.id] === true;
      var placeholder = parseStatus && parseStatus.entries[task.id] === "placeholder (core notation cannot encode this body)";
      var designText = root.N3 && typeof root.N3.isDesign === "function" && root.N3.isDesign(task.definition, task.world);
      host.appendChild(node("p", "ladder-caption", designText ? "Design text (not notation v3 source)" :
        isSource ? "DEFINITION / ASCII SOURCE" : placeholder ?
          "placeholder (core notation cannot encode this body)" : "Design text (not notation v3 source)"));
      if (designText || isSource || root.N3 && root.N3.lookup(task.definition, task.world)) {
        var definition = node("pre", "ladder-prompt");
        definition.appendChild(root.A2.expr(task.definition, { world: task.world, design: !!designText }));
        host.appendChild(definition);
      } else {
        var design = node("p", "ladder-design-text");
        if (root.N3) design.appendChild(root.A2.expr(task.definition, { world: task.world, design: true }));
        else design.textContent = task.definition;
        host.appendChild(design);
      }
      host.appendChild(node("p", "ladder-hint", task.depends_on.length ? "Uses: " + task.depends_on.join(", ") + "." : "Starts the chain."));
    }
    host.appendChild(node("p", "ladder-caption", "PROMPT / TEXT"));
    var prompt = node("p", "ladder-design-text", task.prompt);
    if (root.N3 && root.N3.prose(task.prompt, task.world)) {
      prompt.replaceChildren();
      appendProse(prompt, task.prompt, task.world);
    }
    host.appendChild(prompt);
    var form = node("form", "ladder-form");
    var label = node("label", "", "Your answer / " + task.answer_format.replace(/_/g, " "));
    var input = node("textarea", "ladder-answer");
    input.rows = task.answer_format === "definition" ? 5 : 3;
    input.spellcheck = false;
    input.setAttribute("aria-describedby", "ladder-answer-hint");
    label.appendChild(input);
    form.appendChild(label);
    var hint = node("p", "ladder-hint", offline ?
      "Follow the answer format in the prompt. This form checks shape only; it does not check correctness." : task.answer_format === "value" ?
      "Enter the requested outcome as JSON, a safe integer, true, false, Bottom(reason), or a plain ASCII expression." :
      task.answer_format === "choice" ? "Enter the exact ASCII option." :
        task.answer_format === "definition" ?
          (task.label === "legacy-v1 operations world" ?
            "Enter an ASCII operation definition. This task needs the Python grader." :
            "Enter an ASCII definition or the requested JSON body. This task needs the Python grader.") :
        "Enter JSON in the format shown at the end of the prompt. Arrays use the published input shapes.");
    hint.id = "ladder-answer-hint";
    hint.textContent += " Type answers in the ASCII storage form shown under Copy; the grader does not translate display notation.";
    form.appendChild(hint);
    var actions = node("div", "ladder-actions");
    var submit = node("button", "ladder-primary", offline ? "Prepare offline command" : "Check answer");
    submit.type = "submit";
    actions.appendChild(submit);
    var reveal = node("button", "ladder-secondary", offline ? "Show offline instructions" : "Show the grading recipe");
    reveal.type = "button";
    actions.appendChild(reveal);
    form.appendChild(actions);
    host.appendChild(form);
    host.appendChild(node("p", "ladder-hint", offline ?
      "Browser grading is off for these entries. The form checks answer shape only; run the offline command to grade." :
      "Browser checks are open-book: public hashes over small candidate sets can reveal reference answers. For held-out scoring use the Python grader."));
    var report = node("div", "ladder-report", offline ?
      "Answer format: " + task.answer_format.replace(/_/g, " ") + ". Enter an answer to prepare the offline command. No browser grade is available." :
      "Grader: " + (task.grader.method || "exact_value") + ". Submit an answer to see the report.");
    report.setAttribute("role", "status");
    host.appendChild(report);
    var recipe = node("div", "ladder-reference");
    recipe.id = "ladder-recipe";
    recipe.hidden = true;
    recipe.appendChild(node("p", "ladder-caption", offline ? "OFFLINE GRADING" : "PUBLIC HASH CHECK"));
    recipe.appendChild(node("p", "", offline ?
      "The browser validates the answer format and quotes the JSON answer for a shell command. It does not check correctness. Run the command from the repository root with the project installed. Generate the private grading file locally with PYTHONPATH=src python -m opulse.tasks_v2.challenge_grade --build at build/challenge_v2/grading.json. Set OPULSE_CHALLENGE_GRADING for another local path; it is not tracked in the repository." :
      "The browser encodes your JSON answer with sorted keys, ASCII escapes and no spaces. It hashes UTF-8(task id), a zero byte and the encoded answer with SHA-256. It compares the digest with the public check. Witnesses must also be in the published scope. Definition tasks need the Python grader and its structural and held-out checks."));
    if (!offline) recipe.appendChild(node("p", "ladder-hint", "A digest match checks a submitted value; it does not prove a definition. Finite choices can be recovered offline."));
    host.appendChild(recipe);
    reveal.setAttribute("aria-controls", recipe.id);
    reveal.setAttribute("aria-expanded", "false");
    reveal.addEventListener("click", function () {
      recipe.hidden = !recipe.hidden;
      reveal.setAttribute("aria-expanded", String(!recipe.hidden));
      reveal.textContent = recipe.hidden ? (offline ? "Show offline instructions" : "Show the grading recipe") :
        (offline ? "Hide offline instructions" : "Hide the grading recipe");
    });
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      report.replaceChildren();
      var answer;
      try { answer = parseAnswer(task, input.value, schema); }
      catch (error) { report.appendChild(node("strong", "", error.message)); return; }
      var result = await grade(task, answer, schema);
      if (offline) {
        if (result.status === "invalid") {
          report.appendChild(node("strong", "", "Invalid answer shape or unsupported number for " + task.answer_format.replace(/_/g, " ") + "."));
          return;
        }
        report.appendChild(node("strong", "", "Answer shape accepted locally. Browser grading is off; correctness is not checked."));
        report.appendChild(node("p", "", "Run this command from the repository root with the project installed. First generate the private grading file locally with PYTHONPATH=src python -m opulse.tasks_v2.challenge_grade --build at build/challenge_v2/grading.json. Set OPULSE_CHALLENGE_GRADING for another local path; it is not tracked in the repository:"));
        var offlineCommand = node("pre", "ladder-command");
        offlineCommand.appendChild(node("code", "", pythonCommand(task, answer, schema)));
        report.appendChild(offlineCommand);
        return;
      }
      if (result.status === "python" || result.status === "undecidable") {
        report.appendChild(node("strong", "", result.status === "undecidable" ?
          "Not the reference witness; the browser cannot decide it." : "This task needs the Python grader."));
        report.appendChild(node("p", "", "Grader: " + result.method + ". Run this command from the repository root with Python and the project installed:"));
        var command = node("pre", "ladder-command");
        command.appendChild(node("code", "", pythonCommand(task, answer)));
        report.appendChild(command);
      } else {
        report.appendChild(node("strong", "", result.status === "correct" ? "Matches the public hash check." :
          result.status === "invalid" ? "Invalid answer shape or unsupported number." : "Does not match the public hash check."));
        report.appendChild(node("p", "", "Browser grader: " + result.method + ". " +
          (result.status === "correct" ? "Computed in your browser from the versioned catalogue. No kernel run was made." :
            "Unknown never counts as correct.")));
      }
    });
  }

  function render(host, data, parseStatus) {
    if (!["opulse.challenge_v2/2", "opulse.challenge_v2/3"].includes(data.schema) ||
        !data.ladders || !data.paths || !data.paths.six_kinds_one_world) {
      throw new Error("Unknown challenge catalogue schema");
    }
    if (root.N3 && data.notation3) root.N3.register(data.notation3);
    host.replaceChildren();
    var route = featuredRoute(data);
    var path = node("section", "ladder-route");
    path.appendChild(node("p", "ladder-kicker", "START HERE / KIND ROUTE"));
    path.appendChild(node("h2", "", "The catalogue's featured route"));
    path.appendChild(node("p", "", "Follow the six-kind design route tagged " + route.world + ", or select a separate task below. Spec 0.5 allows pure dependencies for ?sum_numerator; this route has no rebuilt, checked 0.5 export."));
    var links = node("div", "ladder-route-links");
    var angle = "compute";
    var tabs = node("div", "ladder-tabs");
    var list = node("div", "ladder-list");
    var detail = node("section", "ladder-detail");
    var grid = node("div", "ladder-grid");
    detail.id = "ladder-task";
    var guided = node("p", "ladder-route-progress", "Choose a kind or follow the route in order.");
    var guidePosition = 0;
    var next;
    function select(task, focus, fromRoute) {
      grid.classList.toggle("is-guided", !!fromRoute);
      (fromRoute ? path : grid).appendChild(detail);
      renderTask(detail, task, parseStatus, data.schema);
      list.querySelectorAll(".ladder-item").forEach(function (element) {
        element.setAttribute("aria-current", String(!fromRoute && element.dataset.taskId === task.id));
      });
      links.querySelectorAll("button").forEach(function (control) {
        control.setAttribute("aria-current", String(!!fromRoute && control.dataset.taskId === task.id));
      });
      tabs.querySelectorAll("button").forEach(function (tab) {
        tab.setAttribute("aria-pressed", String(!fromRoute && tab.dataset.angle === angle));
      });
      if (fromRoute) {
        guidePosition = route.steps.indexOf(task);
        guided.textContent = "Guided route step " + (guidePosition + 1) + " of " + route.steps.length + ": " + task.kind + ".";
      } else guided.textContent = "Angle ladder selected. Choose a guided route step to return.";
      next.hidden = !fromRoute || guidePosition >= route.steps.length - 1;
      if (focus) { detail.scrollIntoView({ behavior: root.A2.reducedMotion() ? "instant" : "smooth" }); detail.querySelector("h2").setAttribute("tabindex", "-1"); detail.querySelector("h2").focus({ preventScroll: true }); }
    }
    function activate(nextAngle, task) {
      angle = nextAngle;
      list.replaceChildren();
      data.ladders[angle].forEach(function (entry, index) { list.appendChild(item(entry, index, function () { select(entry, true); })); });
      select(task || data.ladders[angle][0], false, false);
    }
    next = button("Next kind", "ladder-route-button", function () {
      if (guidePosition < route.steps.length - 1) select(route.steps[guidePosition + 1], true, true);
    });
    next.hidden = true;
    route.steps.forEach(function (task, index) {
      var control = button(String(index + 1) + " / " + task.name, "ladder-route-button", function () {
        select(task, true, true);
      });
      control.dataset.taskId = task.id;
      control.prepend(root.A2.kindBadge(task.kind));
      links.appendChild(control);
    });
    path.appendChild(links);
    path.appendChild(guided);
    path.appendChild(next);
    host.appendChild(path);
    host.appendChild(node("p", "ladder-kicker ladder-section-title", "ANGLE LADDER / SEPARATE TASKS"));
    ANGLES.forEach(function (name, index) {
      var control = button(String(index + 1).padStart(2, "0") + " / " + name, "ladder-tab", function () { activate(name); });
      control.dataset.angle = name;
      tabs.appendChild(control);
    });
    tabs.setAttribute("role", "group");
    tabs.setAttribute("aria-label", "Task angle filters");
    host.appendChild(tabs);
    var sidebar = node("section", "ladder-sidebar");
    sidebar.appendChild(node("h2", "", "The angle ladder"));
    sidebar.appendChild(node("p", "ladder-hint", "Separate from the guided route. Tasks appear in the catalogue's stored order."));
    sidebar.appendChild(list);
    grid.appendChild(sidebar);
    grid.appendChild(detail);
    host.appendChild(grid);
    activate(angle);
    select(route.steps[0], false, true);
  }

  function appendProse(host, text, world) {
    var segments = root.N3 && root.N3.prose(text, world);
    if (segments) segments.forEach(function (segment) {
      host.appendChild(segment[0] === "f" ? root.N3.render(segment[1], segment[2]) : document.createTextNode(segment[1]));
    });
    else host.textContent = text;
  }

  function mount(host) {
    Promise.all([fetch(DATA_URL), fetch("../../assets/data/atoms2/parse_status.json")]).then(function (responses) {
      if (!responses[0].ok || !responses[1].ok) throw new Error("Catalogue or parse status unavailable");
      return Promise.all(responses.map(function (response) { return response.json(); }));
    }).then(function (values) {
      if (values[1].schema !== "opulse.atoms2_parse_status/1") throw new Error("Unexpected parse status schema");
      render(host, values[0], values[1]);
    }).catch(function () {
      host.replaceChildren(node("p", "ladder-error", "The challenge catalogue could not load. Try again after refreshing the page."));
    });
  }

  var api = { equal: equal, validValue: validValue, outcome: outcome, parseAnswer: parseAnswer,
    canonical: canonical, answerHash: answerHash, grade: grade, pythonCommand: pythonCommand,
    featuredRoute: featuredRoute, renderTask: renderTask, render: render, mount: mount };
  function install() {
    if (!root.A2) return;
    root.A2.ladders = api;
    root.A2.register("ladders", mount);
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, { once: true });
    else install();
  }
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
