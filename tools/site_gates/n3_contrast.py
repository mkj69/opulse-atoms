"""Check rendered notation contrast across page widths and colour schemes."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

if __package__:
    from .n3_roundtrip import page_urls
else:
    from n3_roundtrip import page_urls

COLOUR = re.compile(r"(?:rgba?|color)\([^()]*\)|#[0-9a-fA-F]{3,8}\b|\btransparent\b", re.IGNORECASE)
CHANNELS = 3


def parse_colour(value):
    """Return sRGB channels and alpha in the 0..1 range."""
    value = value.strip().lower()
    if value in ("black", "white"):
        channel = 0.0 if value == "black" else 1.0
        return (channel, channel, channel, 1.0)
    if value == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) in (3, 4):
            digits = "".join(character * 2 for character in digits)
        if len(digits) not in (6, 8):
            raise ValueError(f"unsupported colour: {value}")
        return tuple(int(digits[index:index + 2], 16) / 255 for index in (0, 2, 4)) + (
            int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0,)
    match = re.fullmatch(r"(rgba?|color)\((.*)\)", value)
    if not match:
        raise ValueError(f"unsupported colour: {value}")
    function, arguments = match.groups()
    if function == "color":
        space, _, arguments = arguments.partition(" ")
        if space != "srgb":
            raise ValueError(f"unsupported colour space: {space}")
    parts = [part for part in re.split(r"[,\s/]+", arguments.strip()) if part]
    if len(parts) not in (3, 4):
        raise ValueError(f"unsupported colour: {value}")

    def channel(part):
        number = float(part.rstrip("%"))
        if part.endswith("%"):
            return number / 100
        return number / 255 if function != "color" else number

    channels = tuple(channel(part) for part in parts[:CHANNELS])
    alpha = float(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1) if len(parts) == 4 else 1.0
    if any(not 0 <= component <= 1 for component in (*channels, alpha)):
        raise ValueError(f"out-of-range colour: {value}")
    return (*channels, alpha)


def composite(foreground, background):
    alpha = foreground[3] + background[3] * (1 - foreground[3])
    if not alpha:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple((foreground[index] * foreground[3] + background[index] * background[3] *
                  (1 - foreground[3])) / alpha for index in range(CHANNELS)) + (alpha,)


def luminance(colour):
    channels = [component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4
                for component in colour[:CHANNELS]]
    return sum(weight * component for weight, component in zip((0.2126, 0.7152, 0.0722), channels))


def contrast_ratio(foreground, background):
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def is_large_text(font_size, font_weight):
    weight = {"bold": 700, "bolder": 700, "normal": 400, "lighter": 300}.get(str(font_weight))
    if weight is None:
        weight = int(float(font_weight))
    return float(str(font_size).removesuffix("px")) >= 24 or (
        float(str(font_size).removesuffix("px")) >= 18.66 and weight >= 700)


def backgrounds(chain):
    colours = [(1.0, 1.0, 1.0, 1.0)]
    for layer in reversed(chain):
        solid = parse_colour(layer["backgroundColor"])
        colours = [composite(solid, background) for background in colours]
        image = layer.get("backgroundImage", "none")
        if "gradient(" in image:
            stops = [parse_colour(match.group()) for match in COLOUR.finditer(image)]
            if stops:
                colours = [composite(stop, background) for background in colours for stop in stops]
    return colours


def classify(element):
    ink = parse_colour(element["color"])
    options = backgrounds(element["ancestors"])
    background = min(options, key=lambda option: contrast_ratio(composite(ink, option), option))
    foreground = composite(ink, background)
    ratio = contrast_ratio(foreground, background)
    threshold = 3.0 if is_large_text(element["fontSize"], element["fontWeight"]) else 4.5
    return {"text": element["text"], "where": element.get("where", ""), "color": element["color"],
            "background": background,
            "ratio": round(ratio, 3), "threshold": threshold} if ratio < threshold else None


SETTLE = r"""(() => {
  const style = document.createElement('style');
  style.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; }';
  document.head.appendChild(style);
})()"""


SNAPSHOT = r"""(() => {
  const samples = [];
  for (const element of document.querySelectorAll('.n3, .n3 span')) {
    const ancestors = [];
    let hidden = false;
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) hidden = true;
      ancestors.push({backgroundColor: style.backgroundColor, backgroundImage: style.backgroundImage});
    }
    if (hidden) continue;
    const style = getComputedStyle(element);
    const where = [];
    for (let current = element; current && where.length < 5; current = current.parentElement)
      if (current.className && typeof current.className === 'string') where.push(current.tagName.toLowerCase() + '.' + current.className.trim().split(/\s+/).join('.'));
    for (const node of element.childNodes) {
      if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      if (![...range.getClientRects()].some(rect => rect.width > 0 && rect.height > 0)) continue;
      samples.push({text: node.textContent.trim().slice(0, 120), color: style.color,
        fontSize: style.fontSize, fontWeight: style.fontWeight, ancestors, where: where.join(' < ')});
    }
  }
  return samples;
})()"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path, help="built MkDocs site directory")
    parser.add_argument("--output", type=Path, default=Path("/tmp/opulse-n3-contrast.json"))
    parser.add_argument("--only", action="append", metavar="URL", help="check only this page (repeatable)")
    args = parser.parse_args()
    from sitecheck.browser import Chrome
    from sitecheck.discovery import serve

    root = Path(__file__).resolve().parents[2]
    report = {"site": str(args.site.resolve()), "pages": {}, "findings": []}
    with serve(args.site.resolve()) as base, Chrome(timeout=150) as chrome:
        for url in args.only or page_urls(root):
            report["pages"][url] = {}
            for width in (1440, 390):
                for scheme in ("default", "slate"):
                    label = f"{width}/{scheme}"
                    try:
                        chrome.open(base.rstrip("/") + url, width)
                        chrome.pump(2)
                        # Material animates colour changes; measure the settled colours.
                        chrome.evaluate(SETTLE)
                        chrome.evaluate("document.querySelectorAll('details').forEach(detail => { detail.open = true; });")
                        chrome.evaluate(f"document.querySelectorAll('[data-md-color-scheme]').forEach(element => element.setAttribute('data-md-color-scheme', '{scheme}'));")
                        snapshot = chrome.evaluate(SNAPSHOT)
                        findings = [dict(url=url, width=width, scheme=scheme, **finding)
                                    for sample in snapshot if (finding := classify(sample))]
                        report["pages"][url][label] = {"checked": len(snapshot), "failures": len(findings),
                                                       "worst": sorted(findings, key=lambda item: item["ratio"])[:10]}
                        report["findings"].extend(findings)
                    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                        finding = {"url": url, "width": width, "scheme": scheme, "error": str(error)}
                        report["pages"][url][label] = {"checked": 0, "failures": 1, "worst": [finding]}
                        report["findings"].append(finding)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(report['pages'])} pages; {len(report['findings'])} findings; {args.output}")
    return bool(report["findings"])


if __name__ == "__main__":
    raise SystemExit(main())
