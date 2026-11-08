(function (root) {
  "use strict";
  var A2 = root.A2 || (root.A2 = {});
  function parseFuel(text) {
    if (!/^\d+$/.test(text)) return null;
    var fuel = Number(text);
    return Number.isSafeInteger(fuel) && fuel <= 100000 ? fuel : null;
  }
  function compute(left, right, finalByte, fuel) {
    if (!Array.isArray(left) || !Array.isArray(right) || !left.length || left.length !== right.length || left.length > 32 ||
        !left.concat(right).every(function (value) { return Number.isInteger(value) && value >= 0 && value <= 255; }) ||
        !Number.isInteger(finalByte) || finalByte < 0 || finalByte > 255 || !Number.isSafeInteger(fuel) || fuel < 0) throw new RangeError("Invalid bytes or fuel.");
    var memory = left.slice(); memory[memory.length - 1] = finalByte;
    var registers = { A: 0, B: 0, C: 0, D: 0, pc: 0, z: 0 };
    var wide = 0n, steps = 0, trace = [];
    function snapshot(index, phase, leftByte, rightByte) {
      trace.push({ index: index, phase: phase, left: leftByte, right: rightByte,
        modular: registers.D, wide: wide.toString(), totalSteps: steps, registers: Object.assign({}, registers) });
    }
    snapshot(0, "Ready", memory[0], right[0]);
    for (var index = 0; index < left.length; index++) {
      var a = memory[index], b = right[index];
      if (steps >= fuel) return { outcome: "Unknown(fuel)", steps: steps, next: index, needed: 4 * b + 2,
        modular: registers.D, wideDecimal: wide.toString(), trace: trace, registers: Object.assign({}, registers) };
      registers.A = 0; registers.B = b; registers.C = a;
      var needed = 4 * b + 2;
      function charge(phase) {
        if (steps >= fuel) return false;
        steps++;
        snapshot(index, phase, a, b);
        return true;
      }
      function exhausted() {
        return { outcome: "Unknown(fuel)", steps: steps, next: index, needed: needed - (steps - pairStart),
          modular: registers.D, wideDecimal: wide.toString(), trace: trace, registers: Object.assign({}, registers) };
      }
      var pairStart = steps;
      if (!charge("Branch into pair")) return exhausted();
      for (var counter = 0; counter < b; counter++) {
        if (steps >= fuel) return exhausted();
        registers.A = (registers.A + registers.C) % 256;
        charge("Add C into A");
        if (steps >= fuel) return exhausted();
        registers.B--;
        charge("Decrement B");
        if (steps >= fuel) return exhausted();
        registers.z = Number(registers.B === 0);
        charge("Test zero flag");
        if (steps >= fuel) return exhausted();
        registers.pc = (registers.pc + 1) % 256;
        charge("Advance pc");
      }
      if (steps >= fuel) return exhausted();
      registers.D = (registers.D + registers.A) % 256;
      wide += BigInt(a) * BigInt(b);
      charge("Accumulate dot and wide_dot");
    }
    return { outcome: "Ok", modular: registers.D, wide: [Number(wide % 256n), Number((wide / 256n) % 256n), Number((wide / 65536n) % 256n)],
      wideDecimal: wide.toString(), steps: steps, trace: trace, registers: registers };
  }
  function mount(host) {
    var el = A2.el, fixture, altered = false, activeStep = 0, results = [], runCount = 0, playback = null;
    function formula(text) {
      if (/^[xyABCD]$/.test(text) && (!root.N3 || !root.N3.lookup(text, "computer")))
        return el("span", { text: text });
      return root.N3 && !root.N3.lookup(text, "computer") ?
        el("span", { text: "No source published" }) : A2.expr(text, { world: "computer" });
    }
    var section = el("section", { class: "a2-computer", id: "computer-lab" });
    var worldPicker = el("select", { "aria-label": "Choose a world" }, [
      el("option", { value: "computer", text: "Computer: dot product lab" }),
      el("option", { value: "integer", text: "Integer: definition workshop" }),
      el("option", { value: "roads", text: "Roads: open closure challenge" })
    ]);
    function chooseWorld(world) {
      if (world === "roads") { root.location.assign(new URL("challenge/", root.location.href).href); return; }
      worldPicker.value = world === "integer" ? world : "computer";
      var anchor = world === "integer" ? "definition-workshop" : "computer-lab";
      if (root.location.hash !== "#" + anchor) root.location.hash = anchor;
      else root.document.getElementById(anchor).scrollIntoView();
    }
    var requestedWorld = new URLSearchParams(root.location && root.location.search || "").get("world") ||
      (root.location.hash === "#definition-workshop" ? "integer" : "computer");
    worldPicker.value = requestedWorld === "integer" ? "integer" : "computer";
    if (requestedWorld === "roads") { chooseWorld("roads"); return; }
    worldPicker.addEventListener("change", function () { chooseWorld(worldPicker.value); });
    section.append(el("div", { class: "a2-computer-world" }, [el("label", {}, ["World ", worldPicker])]));
    section.append(el("div", { class: "a2-computer-overline", text: "PLAY / LAB / COMPUTER" }), el("h1", { text: "Same dot. Different wide_dot." }),
      el("p", { text: "Two machines differ only in the final input byte. Their 8-bit dot products lose the carry, but their 24-bit wide_dot results keep it." }));
    section.append(el("aside", { class: "a2-computer-workshop-entry" }, [
      el("strong", { text: "Definition workshop" }),
      el("span", { text: "Preview objects, operations, combinators and observations with finite browser cases. Law and bridge drafts check syntax, sorts and layers only." }),
      el("button", { type: "button", class: "a2-btn", text: "Open the workshop", onclick: function () { chooseWorld("integer"); } })
    ]));
    var panel = el("div", { class: "a2-computer-panel" });
    var badges = el("div", { class: "a2-computer-badges" }, [A2.badge("design"), el("span", { text: "Computed in your browser: computer-lab-preview-1" })]);
    var toggle = el("button", { type: "button", class: "a2-btn", text: "Toggle final byte", "aria-pressed": "false" });
    var fuel = el("input", { type: "number", min: "0", max: "100000", step: "1", value: "5000", id: "a2-computer-fuel" });
    var shortFuel = el("button", { type: "button", class: "a2-btn", text: "Try 256 fuel" });
    var run = el("button", { type: "button", class: "a2-btn", text: "Run machine" });
    var slider = el("input", { type: "range", min: "0", max: "3856", value: "3856", "aria-label": "Charged step" });
    var previous = el("button", { type: "button", class: "a2-btn", text: "Previous step" });
    var next = el("button", { type: "button", class: "a2-btn", text: "Next step" });
    var summary = el("div", { class: "a2-computer-summary" });
    var runStatus = el("p", { class: "a2-computer-run-status", role: "status", text: "Loading public fixture." });
    var machines = el("div", { class: "a2-computer-machines" });
    var stepText = el("output", { class: "a2-computer-step" });
    var method = el("details", { class: "a2-computer-method", open: true }, [el("summary", { text: "What is computed here" }),
      el("p", { text: "Independent browser interpreter computer-lab-preview-1. Each pair charges one branch, four steps per multiplication iteration, then one accumulation. The 12 pairs need 3856 steps. The design's 256 fuel runs out during pair 1 (which needs 478 steps). These are authorized probes of a public fixture, not an editable sealed memory or kernel verification." })]);
    panel.append(badges, summary, runStatus, machines, el("div", { class: "a2-computer-controls" }, [toggle, el("label", {}, ["Layer-0 fuel ", fuel]), shortFuel, run]),
      el("div", { class: "a2-computer-controls a2-computer-scrub" }, [previous, slider, next, stepText]), method);
    section.append(panel); host.append(section);
    function value(text, marked) {
      return el("span", { class: "a2-computer-value" + (marked ? " a2-computer-different" : ""), text: String(text) });
    }
    function machine(result, variant, moment, different) {
      var last = fixture.left.length - 1;
      var finalByte = variant ? fixture.alternateFinalByte : fixture.left[last];
      var card = el("section", { class: "a2-computer-machine" + (altered === Boolean(variant) ? " a2-computer-selected" : ""),
        "aria-label": variant ? "Toggled final byte machine" : "Given final byte machine" });
      var title = el("div", { class: "a2-computer-machine-head" }, [el("strong", { text: variant ? "B / Toggled final byte: " + finalByte : "A / Given final byte: " + finalByte }), A2.badge("design")]);
      var vectors = el("div", { class: "a2-computer-vectors" });
      [["x", fixture.left], ["y", fixture.right]].forEach(function (row) {
        var cells = el("div", { class: "a2-computer-cells" });
        row[1].forEach(function (byte, index) {
          var shown = row[0] === "x" && index === last ? finalByte : byte;
          cells.append(el("span", { class: "a2-computer-byte" + (index === moment.index ? " a2-computer-active" : "") +
            (row[0] === "x" && index === last ? " a2-computer-last" : ""), "aria-label": row[0] + " byte " + (index + 1) + ": " + shown,
          }, [el("small", { text: String(index + 1) }), value(shown, row[0] === "x" && index === last && Boolean(variant))]));
        });
        vectors.append(el("div", { class: "a2-computer-vector" }, [formula(row[0]), cells]));
      });
      var registerBox = el("div", { class: "a2-computer-registers", "aria-label": "Registers at charged step " + activeStep });
      ["A", "B", "C", "D"].forEach(function (name) {
        registerBox.append(el("div", { class: "a2-computer-register" }, [formula(name), value(moment.registers[name])]));
      });
      var finished = result.outcome === "Ok" && activeStep === result.steps;
      var outcome = el("div", { class: "a2-computer-outcome" }, [
        el("div", {}, [formula("dot(x, y)"), value(finished ? result.modular : moment.modular)]),
        el("div", {}, [formula("wide_dot(x, y)"), value(finished ? result.wideDecimal : moment.wide, different && finished)]),
      ]);
      var state = result.outcome !== "Ok" ? "Fuel exhausted during pair " + (result.next + 1) + ". " + result.needed + " more steps needed." :
        finished ? "Completed. Wide result bytes: " + result.wide.join(", ") + ". " + result.steps + " charged steps." : "Partial state, not a final result.";
      var meter = el("div", { class: "a2-computer-fuel" }, [el("span", { text: "Fuel left: " + Math.max(0, Number(fuel.value) - activeStep) }),
        el("div", { class: "a2-computer-fuel-track", role: "progressbar", "aria-label": "Fuel remaining", "aria-valuemin": "0", "aria-valuemax": String(fuel.value),
          "aria-valuenow": String(Math.max(0, Number(fuel.value) - activeStep)) }, [el("div", { class: "a2-computer-fuel-fill", style: "width:" +
            (Number(fuel.value) ? 100 * Math.max(0, Number(fuel.value) - activeStep) / Number(fuel.value) : 0) + "%" })])]);
      card.append(title, vectors, el("div", { class: "a2-computer-readout" }, [registerBox, outcome]), meter,
        el("p", { class: "a2-computer-state" + (result.outcome !== "Ok" ? " a2-computer-unknown" : ""), text: state }));
      return card;
    }
    function display() {
      if (!fixture || !results.length) return;
      var given = results[0], toggled = results[1], moment = given.trace[activeStep];
      var finished = given.outcome === "Ok" && activeStep === given.steps;
      var different = finished && given.wideDecimal !== toggled.wideDecimal;
      summary.replaceChildren(finished ? el("strong", {}, ["Modular results match (", value(given.modular), "). Wide results differ: ",
        value(given.wideDecimal, true), " vs ", value(toggled.wideDecimal, true), "."]) :
        el("strong", { text: given.outcome === "Ok" ? "Partial state. Move to the last step to compare." : "Fuel exhausted: no final result at this fuel." }));
      var selected = altered ? toggled : given;
      machines.replaceChildren(machine(selected, altered ? 1 : 0, selected.trace[activeStep], different));
      toggle.setAttribute("aria-pressed", String(altered));
      stepText.textContent = "Step " + activeStep + " / " + (given.outcome === "Ok" ? given.steps : Number(fuel.value)) +
        "; pair " + (moment.index + 1) + "/" + fixture.left.length + "; " + moment.phase;
      slider.value = String(activeStep);
      previous.disabled = activeStep === 0;
      next.disabled = activeStep >= Number(slider.max);
    }
    function validFuel() { return parseFuel(fuel.value) !== null; }
    function invalidFuel() {
      results = [];
      machines.replaceChildren();
      summary.textContent = "No result at this fuel.";
      runStatus.textContent = "Enter a whole-number fuel from 0 to 100000.";
      slider.disabled = true; previous.disabled = true; next.disabled = true;
    }
    function runMachine(initial, announce = true) {
      clearInterval(playback);
      if (!fixture) return;
      if (!validFuel()) { invalidFuel(); return; }
      var budget = parseFuel(fuel.value);
      results = [compute(fixture.left, fixture.right, fixture.left[fixture.left.length - 1], budget),
        compute(fixture.left, fixture.right, fixture.alternateFinalByte, budget)];
      slider.max = String(results[0].trace.length - 1);
      slider.disabled = false;
      activeStep = initial === true ? Number(slider.max) : 0;
      runCount++;
      if (announce) announcePlayback(runStatus, "manual", "Run " + runCount + " ready at step " + activeStep + ". " + results[0].outcome + " after " + results[0].steps + " charged steps.");
      display();
    }
    toggle.addEventListener("click", function () { if (!fixture) return; altered = !altered; runMachine(false, false); runStatus.textContent = "Final input byte switched to " + (altered ? fixture.alternateFinalByte : fixture.left[fixture.left.length - 1]) + ". Run " + runCount + " is at step 0; use the scrubber to inspect it."; });
    shortFuel.addEventListener("click", function () { fuel.value = "256"; runMachine(); });
    run.addEventListener("click", function () {
      runMachine(false, false);
      if (!results.length) return;
      if (root.matchMedia && root.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        runStatus.textContent = "Run " + runCount + " ready at step 0. Reduced motion: use the scrubber to inspect each step.";
        return;
      }
      announcePlayback(runStatus, "start", "Run " + runCount + " playing. Use the scrubber to inspect steps.");
      playback = setInterval(function () {
        activeStep = Math.min(Number(slider.max), activeStep + Math.max(1, Math.ceil(Number(slider.max) / 20)));
        display();
        if (activeStep >= Number(slider.max)) {
          clearInterval(playback); playback = null;
          announcePlayback(runStatus, "end", "Run " + runCount + " complete: " + results[altered ? 1 : 0].outcome + " after " + activeStep + " charged steps.");
        }
      }, 110);
    });
    fuel.addEventListener("input", function () {
      clearInterval(playback); playback = null; results = [];
      machines.replaceChildren();
      summary.textContent = "Fuel changed. Run again to compute a result.";
      runStatus.textContent = validFuel() ? "Fuel changed; previous results are stale. Run machine to recompute." : "Enter a whole-number fuel from 0 to 100000.";
      stepText.textContent = "No current trace";
      slider.disabled = true; previous.disabled = true; next.disabled = true;
    });
    function reportStep() { display(); announcePlayback(runStatus, "manual", stepText.textContent); }
    slider.addEventListener("input", function () { clearInterval(playback); playback = null; activeStep = Number(slider.value); reportStep(); });
    previous.addEventListener("click", function () { clearInterval(playback); playback = null; activeStep = Math.max(0, activeStep - 1); reportStep(); });
    next.addEventListener("click", function () { clearInterval(playback); playback = null; activeStep = Math.min(Number(slider.max), activeStep + 1); reportStep(); });
    fetch("../assets/data/atoms2/computer.json").then(function (response) { if (!response.ok) throw new Error("Fixture unavailable."); return response.json(); })
      .then(function (data) { if (root.N3 && data.notation3) root.N3.register(data.notation3); fixture = data; runMachine(true, false); runStatus.textContent = "Public fixture ready. Use the scrubber or run the machine."; })
      .catch(function (error) { summary.textContent = error.message; });
  }
  function announcePlayback(status, phase, message) {
    if (phase !== "tick") status.textContent = message;
  }
  A2.computerLab = { compute: compute, parseFuel: parseFuel, announcePlayback: announcePlayback, mount: mount };
  if (A2.register) A2.register("computerLab", mount);
  if (typeof module !== "undefined" && module.exports) module.exports = A2.computerLab;
})(typeof window !== "undefined" ? window : globalThis);
