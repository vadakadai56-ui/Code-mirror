"""Stage 3 browser tests: the flowchart is drawn correctly for every example."""

import pytest

from mirror.examples import EXAMPLES
from mirror.graph_builder import build_graph
from tests.e2e.conftest import load_example

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
    assert page.locator("#stdout").inner_text().strip() == "5! = 120"


def test_syntax_error_is_shown_and_line_marked(page):
    page.fill("#code", "x = 1\nif x > 0\n    print(x)\n")
    page.click("#visualize-btn")
    page.wait_for_selector("#message:not([hidden])")
    assert "Syntax error" in page.inner_text("#message")
    assert "line 2" in page.inner_text("#message")
    assert page.locator("#gutter .is-error").inner_text() == "2"
    assert page.locator(".flowchart").count() == 0


def test_blocked_import_is_explained(page):
    page.fill("#code", "import os\nprint(os.getcwd())\n")
    page.click("#visualize-btn")
    page.wait_for_selector("#message:not([hidden])")
    text = page.inner_text("#message")
    assert "Not allowed in Code Mirror" in text and "Importing 'os' is not allowed" in text


def test_timeout_is_explained(page):
    page.fill("#code", "total = sum(range(10 ** 12))\n")
    page.click("#visualize-btn")
    page.wait_for_selector("#message:not([hidden])", timeout=10_000)
    assert "Time limit reached" in page.inner_text("#message")
