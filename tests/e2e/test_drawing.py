"""Stage 3 browser tests: the flowchart is drawn correctly for every example."""

import pytest

from mirror.examples import EXAMPLES
from mirror.graph_builder import build_graph
from tests.e2e.conftest import load_example, visualize

SHOTS = "tests/e2e/screenshots"


@pytest.mark.parametrize("example", EXAMPLES, ids=lambda e: e["id"])
def test_every_node_and_edge_is_drawn(page, example):
    load_example(page, example["id"])
    graph = build_graph(example["code"])

    assert page.locator(".flowchart .node").count() == len(graph["nodes"])
    assert page.locator(".flowchart .edge").count() == len(graph["edges"])
    assert page.locator(".lane__title").all_text_contents() == [lane["title"] for lane in graph["lanes"]]
    for node_type in {n["type"] for n in graph["nodes"]}:
        expected = sum(1 for n in graph["nodes"] if n["type"] == node_type)
        assert page.locator(f".flowchart .node--{node_type}").count() == expected

    # no two nodes overlap
    boxes = [page.locator(".flowchart .node").nth(i).bounding_box() for i in range(len(graph["nodes"]))]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] and \
                a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]
            assert not overlap

    page.screenshot(path=f"{SHOTS}/{example['id']}.png")
    assert page.errors == []


def test_output_panel_shows_program_output(page):
    load_example(page, "factorial")
    assert page.locator("#stdout").inner_text() == ""  # step 1: nothing printed yet
    page.click("#btn-last")
    assert page.locator("#stdout").inner_text().strip() == "5! = 120"


def test_syntax_error_is_shown_and_line_marked(page):
    visualize(page, "x = 1\nif x > 0\n    print(x)\n")
    page.wait_for_selector("#message:not([hidden])")
    assert "Syntax error" in page.inner_text("#message")
    assert "line 2" in page.inner_text("#message")
    assert page.locator("#gutter .is-error").inner_text() == "2"
    assert page.locator(".flowchart").count() == 0


def test_blocked_import_is_explained(page):
    visualize(page, "import os\nprint(os.getcwd())\n")
    page.wait_for_selector("#message:not([hidden])")
    text = page.inner_text("#message")
    assert "Not allowed in Code Mirror" in text and "Importing 'os' is not allowed" in text


def test_timeout_is_explained(page):
    visualize(page, "total = sum(range(10 ** 12))\n")
    page.wait_for_selector("#message:not([hidden])", timeout=10_000)
    assert "Time limit reached" in page.inner_text("#message")


def test_example_deep_link(browser, base_url):
    from tests.e2e.conftest import make_page
    page = browser.new_context().new_page()
    page.goto(f"{base_url}/?example=factorial")
    page.wait_for_selector(".flowchart .node")
    assert page.input_value("#example-select") == "factorial"
    assert "factorial(5)" in page.input_value("#code")
    page.select_option("#example-select", "fizzbuzz")
    page.wait_for_function("location.search === '?example=fizzbuzz'")
    page.context.close()


def test_skip_link_and_live_regions(page):
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "skip-link"
    page.keyboard.press("Enter")
    assert page.evaluate("document.activeElement.id") == "code"
    page.click("#btn-play")
    assert page.get_attribute("#step-label", "aria-live") == "off"
    page.click("#btn-play")
    assert page.get_attribute("#step-label", "aria-live") == "polite"


def test_phone_width_has_no_sideways_page_scroll(browser, base_url):
    page = browser.new_context(viewport={"width": 390, "height": 900}).new_page()
    page.goto(base_url)
    page.wait_for_selector(".flowchart .node")
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    page.context.close()
