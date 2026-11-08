(function (root) {
  "use strict";

  function enhance(container) {
    if (root.N3 && root.A2 && root.A2.kernelData && root.A2.kernelData.notation3)
      root.N3.register(root.A2.kernelData.notation3);
    if (root.N3) container.querySelectorAll("code").forEach(function (code) {
      if (code.classList.contains("n3") || code.closest("pre")) return;
      var entry = root.N3.lookup(code.textContent);
      if (entry) code.replaceWith(root.N3.render(entry.display, entry.ascii));
    });
    var tables = container.querySelectorAll("table");
    tables.forEach(function (table, index) {
      if (table.closest(".a2-spec-table-scroll")) return;
      var cue = document.createElement("p");
      cue.className = "a2-spec-table-cue";
      cue.id = "a2-spec-table-cue-" + index;
      cue.textContent = "Table continues sideways. Focus the table and use arrow keys to scroll.";
      var wrapper = document.createElement("div");
      wrapper.classList.add("a2-spec-table-scroll");
      wrapper.setAttribute("tabindex", "0");
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", "Scrollable specification table " + (index + 1));
      wrapper.setAttribute("aria-describedby", cue.id);
      table.parentNode.insertBefore(cue, table);
      table.parentNode.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { enhance: enhance };
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () {
      enhance(document.querySelector(".md-content__inner.md-typeset"));
    });
    else enhance(document.querySelector(".md-content__inner.md-typeset"));
  }
})(typeof window !== "undefined" ? window : globalThis);
