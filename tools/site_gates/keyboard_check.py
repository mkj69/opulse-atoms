"""Keyboard focus checks on the built site through Chrome DevTools key events."""
import json
import sys
from pathlib import Path

from sitecheck.browser import Chrome
from sitecheck.discovery import serve

SITE = Path(sys.argv[1])


def key(chrome, name, code, vk, text=None):
    for kind in ("keyDown", "keyUp"):
        params = {"type": kind if (kind == "keyUp" or text is None) else "keyDown", "key": name, "code": code,
                  "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        if text and kind == "keyDown":
            params["text"] = text
        chrome.call("Input.dispatchKeyEvent", params)
    chrome.pump(0.25)


def active(chrome):
    return chrome.evaluate("""(() => { const a = document.activeElement; if (!a) return null;
      return {tag: a.tagName, text: (a.textContent || '').trim().slice(0, 50), label: a.getAttribute('aria-label'),
        pressed: a.getAttribute('aria-pressed'), current: a.getAttribute('aria-current')}; })()""")


def focus(chrome, selector):
    return chrome.evaluate(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return false; e.focus(); return document.activeElement === e; }})()")


results = []
with serve(SITE) as base, Chrome() as chrome:
    base = base.rstrip("/")

    def check(name, ok, detail):
        results.append((name, bool(ok), detail))

    # Home: first tower rows selectable by keyboard; roads Next step keeps focus.
    chrome.open(base + "/", 1440)
    chrome.pump(2)
    ok = focus(chrome, "[data-a2='first-tower'] button.a2-btn")
    before = active(chrome)
    key(chrome, "Enter", "Enter", 13, "\r")
    after = active(chrome)
    check("home first-tower Enter keeps focus on a control", ok and after and after["tag"] == "BUTTON", [before, after])
    ok = focus(chrome, "[data-roads-next]")
    key(chrome, " ", "Space", 32, " ")
    after = active(chrome)
    check("home roads Next via Space keeps focus", ok and after and after["tag"] == "BUTTON", after)

    # Evidence drawer: Enter opens it from a badge, Escape closes it and returns focus to the badge.
    chrome.open(base + "/", 1440)
    chrome.pump(2)
    ok = focus(chrome, "[data-a2='first-tower'] button:not(.a2-btn)")
    before = active(chrome)
    key(chrome, "Enter", "Enter", 13, "\r")
    opened = chrome.evaluate("!!document.querySelector('.a2-evidence-drawer') && document.activeElement.closest('.a2-evidence-drawer') !== null")
    key(chrome, "Escape", "Escape", 27)
    after = active(chrome)
    closed = chrome.evaluate("!document.querySelector('.a2-evidence-drawer')")
    check("evidence drawer opens on Enter, Escape closes it and restores focus",
          ok and opened and closed and after and before and after["text"] == before["text"], [before, opened, closed, after])

    # Learn: dependency path button keeps focus after selection (rv8-1).
    chrome.open(base + "/learn/", 1440)
    chrome.pump(2)
    ok = focus(chrome, "[data-roads-path] button")
    before = active(chrome)
    key(chrome, "Enter", "Enter", 13, "\r")
    after = active(chrome)
    check("learn path Enter keeps focus on same definition", ok and after and before and after["text"] == before["text"], [before, after])

    # Worlds: Show all worlds moves focus to a revealed link (rv8-2).
    chrome.open(base + "/worlds/", 1440)
    chrome.pump(2)
    ok = chrome.evaluate("(() => { const b = document.querySelector('button.w2-more:not([hidden])'); if (!b) return false; b.focus(); return true; })()")
    key(chrome, "Enter", "Enter", 13, "\r")
    after = active(chrome)
    check("worlds Show all moves focus to a link", ok and after and after["tag"] == "A", after)

    # Worlds detail: rail arrow keys move selection.
    chrome.open(base + "/worlds/integer/", 1440)
    chrome.pump(2)
    ok = focus(chrome, ".w2-rail-button")
    before = active(chrome)
    key(chrome, "ArrowRight", "ArrowRight", 39)
    after = active(chrome)
    check("world rail ArrowRight moves to next row", ok and after and before and after["text"] != before["text"] and after["pressed"] == "true", [before, after])

    # Play boundary: kind toggle keeps focus after redraw (play13).
    chrome.open(base + "/play/", 1440)
    chrome.pump(3)
    # The boundary appears once a tower exists and a call is used.
    chrome.click_text("Build four-kind preview")
    chrome.pump(2)
    chrome.click_text("Use it")
    chrome.pump(2)
    ok = focus(chrome, "[data-boundary-control^='kind:']:not([disabled])")
    before = active(chrome)
    key(chrome, "Enter", "Enter", 13, "\r")
    after = active(chrome)
    check("play boundary kind toggle keeps focus", ok and after and before and after["label"] != None and after["tag"] == "BUTTON", [before, after])

    # Ladders: tab through angle filters, Enter selects.
    chrome.open(base + "/play/ladders/", 1440)
    chrome.pump(2)
    ok = focus(chrome, ".ladder-tab")
    key(chrome, "Tab", "Tab", 9)
    before = active(chrome)
    key(chrome, "Enter", "Enter", 13, "\r")
    after = active(chrome)
    check("ladders angle filter Enter presses it", ok and after and after.get("pressed") == "true", [before, after])

    findings = chrome.event_findings()

for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name, "" if ok else json.dumps(detail)[:300])
print("js findings:", json.dumps(findings)[:600])
