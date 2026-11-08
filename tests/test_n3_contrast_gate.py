"""Pure contrast calculations and rendered notation chip coverage."""

from pathlib import Path

import pytest

from tools.site_gates.n3_contrast import (
    SNAPSHOT,
    backgrounds,
    classify,
    composite,
    contrast_ratio,
    is_large_text,
    parse_colour,
)


def sample(color="rgb(255, 255, 255)", background="rgb(0, 0, 0)", **changes):
    return {"text": "♦₁", "color": color, "fontSize": "16px", "fontWeight": "500",
            "ancestors": [{"backgroundColor": background, "backgroundImage": "none"}], **changes}


@pytest.mark.parametrize(("value", "expected"), [
    ("rgb(255, 0, 128)", (1, 0, 128 / 255, 1)),
    ("rgba(100%, 0%, 0%, 50%)", (1, 0, 0, .5)),
    ("rgb(0 0 255 / 0.25)", (0, 0, 1, .25)),
    ("color(srgb 0.5 0 1 / 0.75)", (.5, 0, 1, .75)),
    ("#f08c", (1, 0, 136 / 255, 204 / 255)),
    ("transparent", (0, 0, 0, 0)),
])
def test_parse_colour(value, expected):
    assert parse_colour(value) == pytest.approx(expected)


def test_alpha_compositing_and_contrast():
    result = composite(parse_colour("rgba(255, 0, 0, .5)"), parse_colour("rgb(0, 0, 255)"))
    assert result == pytest.approx((.5, 0, .5, 1))
    assert contrast_ratio(parse_colour("black"), parse_colour("white")) == 21


def test_backgrounds_composite_layers_and_gradient_stops():
    chain = [{"backgroundColor": "rgba(255, 0, 0, .5)", "backgroundImage": "none"},
             {"backgroundColor": "rgb(0, 0, 255)", "backgroundImage": "none"}]
    assert backgrounds(chain)[0] == pytest.approx((.5, 0, .5, 1))
    chain[0] = {"backgroundColor": "transparent", "backgroundImage":
                "linear-gradient(90deg, rgb(0, 0, 0) 0%, color(srgb 1 1 1) 100%)"}
    assert backgrounds(chain) == [(0, 0, 0, 1), (1, 1, 1, 1)]


def test_large_text_thresholds():
    assert is_large_text("24px", "400")
    assert is_large_text("18.66px", "700")
    assert not is_large_text("18.65px", "700")
    assert not is_large_text("18.66px", "600")


def test_invisible_given_ink_is_a_finding_but_contrasting_ink_is_not():
    assert classify(sample("rgb(29, 138, 78)", "rgb(29, 138, 78)"))["ratio"] == 1
    assert classify(sample("rgb(0, 0, 0)", "rgb(29, 138, 78)")) is None


def test_classification_uses_worst_gradient_stop_and_large_text_rule():
    element = sample("rgb(255, 255, 255)", "transparent", fontSize="24px", ancestors=[{
        "backgroundColor": "transparent", "backgroundImage":
        "linear-gradient(rgb(255, 255, 255), rgb(0, 0, 0))"}])
    assert classify(element)["ratio"] == 1
    assert classify(sample("rgb(255, 255, 255)", "rgb(180, 180, 180)",
                           fontSize="24px"))["threshold"] == 3


def test_translucent_text_and_gradient_without_colour_stops():
    element = sample("rgba(0, 0, 0, 0.1)", "rgb(255, 255, 255)")
    assert classify(element)["ratio"] < 4.5
    element["ancestors"][0]["backgroundImage"] = "linear-gradient(currentColor, currentColor)"
    assert classify(element)["ratio"] < 4.5


def test_css_chip_ink_covers_filled_marks_and_all_nested_glyphs():
    css = (Path(__file__).resolve().parents[1] / "docs/assets/css/atoms2.css").read_text()
    assert ':is(.a2-tok-given, .a2-chip:not(.a2-invented), .a2-x-given)' in css
    assert '.n3 * { color: inherit; }' in css
    assert "document.querySelectorAll('.n3, .n3 span')" in SNAPSHOT
    assert "detail.open = true" in (Path(__file__).resolve().parents[1] /
                                     "tools/site_gates/n3_contrast.py").read_text()


def test_gate_measures_settled_colours_and_reports_where():
    from tools.site_gates import n3_contrast

    assert "transition: none !important" in n3_contrast.SETTLE
    assert "where" in SNAPSHOT
    finding = classify(sample("rgb(29, 138, 78)", "rgb(29, 138, 78)", where="span.n3-k-object < span.n3"))
    assert finding["where"] == "span.n3-k-object < span.n3"
