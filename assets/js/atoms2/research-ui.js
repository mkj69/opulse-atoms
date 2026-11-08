(function (root) {
  "use strict";
  var scriptUrl = typeof document !== "undefined" && document.currentScript ? document.currentScript.src : "";

  function notation(text, explicit) {
    if (explicit) return "expr";
    if (/^[@?#~][A-Za-z_][A-Za-z_0-9]*$/.test(text)) return "token";
    if (/^[A-Z][A-Za-z_0-9]*<[^<>]+>$/.test(text)) return "expr";
    if (/^(?:obj|op|comb|obs|law|bridge)\s+[A-Za-z_@?#~]/.test(text)) return "expr";
    if (/^(?:[@?#~]?[A-Za-z_][A-Za-z_0-9]*(?:\[[^\]]+\])?)\(.+\)$/.test(text)) return "expr";
    if (/^\?[A-Za-z_][A-Za-z_0-9]*\{[^{}]+\}$/.test(text)) return "expr";
    if (/^by\s+#[A-Za-z_][A-Za-z_0-9]*$/.test(text)) return "expr";
    return null;
  }

  function renderInline(container, kit) {
    if (!container || !kit || !kit.expr || !kit.token) return 0;
    var count = 0;
    container.querySelectorAll("code").forEach(function (code) {
      var text = code.textContent;
      var entry = root.N3 && root.N3.lookup(text);
      if ((code.closest("pre") && !entry) || code.classList.contains("n3") || code.classList.contains("a2-expr") || code.closest(".a2-expr")) return;
      var kind = notation(text, code.hasAttribute && code.hasAttribute("data-a2-expr"));
      if (root.N3 && !entry) return;
      if (!entry && !kind) return;
      if (entry) code.replaceWith(root.N3.render(entry.display, entry.ascii));
      else code.replaceWith(kind === "token" ? kit.token(text, { world: undefined }) : kit.expr(text, { world: undefined }));
      count += 1;
    });
    return count;
  }

  function wrapTables(page) {
    page.querySelectorAll("table").forEach(function (table) {
      if (table.closest(".ar-glossary") || table.closest(".ar-table-scroll")) return;
      var headers = Array.from(table.querySelectorAll("thead th"), function (cell) { return cell.textContent.trim(); });
      var stacked = headers.length >= 3;
      if (stacked) {
        table.querySelectorAll("tbody tr").forEach(function (row) {
          row.querySelectorAll("td").forEach(function (cell, index) {
            cell.setAttribute("data-label", headers[index] || "Field");
          });
        });
      }
      var wrapper = document.createElement("div");
      wrapper.className = stacked ? "ar-table-scroll ar-table-stack" : "ar-table-scroll";
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", stacked ? "Reference table, grouped by row" : "Scrollable reference table");
      wrapper.setAttribute("tabindex", "0");
      var cue = document.createElement("p");
      cue.className = "ar-scroll-cue";
      cue.textContent = stacked ? "Each row shows its fields below." : "Scroll sideways to see every column.";
      table.parentNode.insertBefore(cue, table);
      table.parentNode.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }

  function researchEvidence(source, raw, href) {
    if (source === "bundle") {
      if (raw.schema !== "opulse.research_bundle/1" || !raw.files || !raw.world_lock_hash) throw new Error("Unexpected bundle manifest");
      return {scope: {description: "Source-pinned design bundle with an action@1 task-ID split. No action@2 episodes or evaluation run. Missing: " + raw.not_available.join("; ")},
        artifact: {file: "docs/research/bundles/action-audit-v1/MANIFEST.json", href: href,
          schema: raw.schema, world_hash: raw.world_lock_hash}};
    }
    if (source === "audit") {
      if (raw.status !== "designed-example") throw new Error("Unexpected audit template status");
      return {scope: {
        description: "Proposed scope: " + raw.proposed_scope + ". No run result, seed, or checker artifact recorded."
      }, artifact: {file: "docs/research/action-audit-v1.json", href: href, schema: raw.schema}};
    }
    if (raw.world !== source || raw.schema !== "opulse.world_v2_export/1") throw new Error("Unexpected research export");
    return {scope: {
      description: "World design record with historical export; no policy, model or ablation result."
    }, artifact: {file: "docs/assets/data/worlds_v2/" + source + ".json", href: href,
      schema: raw.schema, version: raw.version}};
  }

  function renderBadges(page, kit, scriptUrl) {
    var badges = page.querySelectorAll("[data-research-source]");
    var sources = Array.from(new Set(Array.from(badges, function (badge) { return badge.dataset.researchSource; })));
    return Promise.all(sources.map(function (source) {
      var url = new URL(source === "bundle" ? "../../../research/bundles/action-audit-v1/MANIFEST.json" :
        source === "audit" ? "../../../research/action-audit-v1.json" :
        "../../data/worlds_v2/" + source + ".json", scriptUrl);
      return fetch(url).then(function (response) {
        if (!response.ok) throw new Error("Research source unavailable");
        return response.json();
      }).then(function (raw) {
        if (root.N3 && raw.notation3) root.N3.register(raw.notation3);
        if (root.N3) renderInline(page, kit);
        var record = researchEvidence(source, raw, url.pathname);
        page.querySelectorAll('[data-research-source="' + source + '"]').forEach(function (badge) {
          var button = kit.badge("design", {record: record});
          button.classList.add("ar-badge");
          badge.replaceWith(button);
        });
      });
    }));
  }

  function renderManifest(page, fetchJson) {
    var panel = page.querySelector("[data-research-manifest]");
    if (!panel) return Promise.resolve();
    var url = new URL(panel.dataset.researchManifest, document.baseURI);
    return fetchJson(url).then(function (raw) {
      if (root.N3 && raw.notation3) root.N3.register(raw.notation3);
      if (raw.schema !== "opulse.research_bundle/1" || !raw.files || !Array.isArray(raw.not_available)) throw new Error("Unexpected bundle manifest");
      var heading = document.createElement("h4");
      heading.textContent = "Manifest: " + raw.world + " source bundle";
      var summary = document.createElement("p");
      summary.textContent = "Stored world lock: " + raw.world_lock_hash + ". No evaluation run.";
      var list = document.createElement("ul");
      Object.keys(raw.files).sort().forEach(function (name) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        link.href = new URL(name, url).href;
        link.textContent = name;
        item.appendChild(link);
        item.appendChild(document.createTextNode(" SHA-256: " + raw.files[name].sha256));
        list.appendChild(item);
      });
      var unavailable = document.createElement("p");
      unavailable.textContent = "Not available: " + raw.not_available.join("; ") + ".";
      panel.replaceChildren(heading, summary, list, unavailable);
    });
  }

  function mount() {
    document.querySelectorAll(".ar-page").forEach(function (page) {
      renderInline(page, root.A2);
      wrapTables(page);
      renderBadges(page, root.A2, scriptUrl).catch(function () {});
      renderManifest(page, function (url) { return fetch(url).then(function (response) {
        if (!response.ok) throw new Error("Bundle manifest unavailable");
        return response.json();
      }); }).catch(function () {});
    });
  }


  if (typeof module !== "undefined" && module.exports) module.exports = { renderInline: renderInline, notation: notation, wrapTables: wrapTables, researchEvidence: researchEvidence, renderBadges: renderBadges, renderManifest: renderManifest };
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
    else mount();
  }
})(typeof window !== "undefined" ? window : globalThis);
