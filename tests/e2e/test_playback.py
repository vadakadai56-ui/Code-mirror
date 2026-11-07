"""Stage 4 browser tests: stepping, playing, clicking nodes, variables panel."""

import pytest

from mirror.examples import EXAMPLES
from mirror.graph_builder import build_graph
from mirror.runner import run_code
from tests.e2e.conftest import load_example, visualize
from tests.test_tracer import node_for_step

CODE = {e["id"]: e["code"] for e in EXAMPLES}


def active_node(page):
    return page.locator(".node.is-active").get_attribute("data-id")


def step_label(page):
    return page.inner_text("#step-label")


def go_to_step(page, i):
    """Move the step slider (what a user dragging it does)."""
    page.eval_on_selector("#step-slider", "(el, i) => { el.value = i; el.dispatchEvent(new Event('input')); }", i)


@pytest.mark.parametrize("example_id", ["fibonacci", "factorial"])
def test_each_step_highlights_the_right_node_and_line(page, example_id):
    load_example(page, example_id)
    graph, trace = build_graph(CODE[example_id]), run_code(CODE[example_id])
    steps = trace["steps"]
    assert step_label(page) == f"Step 1 of {len(steps)}"

    # Walk forward with the button and compare with the Python-side join.
    for i, step in enumerate(steps[:30]):
        if i:
            page.click("#btn-forward")
        assert active_node(page) == node_for_step(graph, step), f"step {i}"
        expected_line = step["line"] if step["event"] == "line" else (
            next(n for n in graph["nodes"] if n["id"] == node_for_step(graph, step))["line"] or step["line"])
        if expected_line:
            assert page.locator("#gutter .is-active").inner_text() == str(expected_line)
        else:  # the program's own start/end have no source line
            assert page.locator("#gutter .is-active").count() == 0
    assert page.errors == []


def test_last_step_shows_full_output_and_disables_forward(page):
    load_example(page, "fizzbuzz")
    page.click("#btn-last")
    total = len(run_code(CODE["fizzbuzz"])["steps"])
    assert step_label(page) == f"Step {total} of {total}"
    assert page.inner_text("#stdout").strip().endswith("FizzBuzz")
    assert page.is_disabled("#btn-forward") and not page.is_disabled("#btn-back")
    page.click("#btn-first")
    assert step_label(page) == f"Step 1 of {total}"
    assert page.inner_text("#stdout") == ""


def test_output_grows_while_stepping(page):
    load_example(page, "fizzbuzz")
    trace = run_code(CODE["fizzbuzz"])
    i = next(k for k, s in enumerate(trace["steps"]) if s["stdout_len"] > 0)
    go_to_step(page, i)
    assert page.inner_text("#stdout") == trace["stdout"][: trace["steps"][i]["stdout_len"]]


def test_variables_panel_and_changes(page):
    load_example(page, "fibonacci")
    trace = run_code(CODE["fibonacci"])
    # first step inside the while loop body where `a` changes
    i = next(k for k, s in enumerate(trace["steps"]) if s["func"] == "fibonacci" and s["line"] == 6)
    go_to_step(page, i - 1)
    page.click("#btn-forward")
    rows = dict(zip(page.locator("#vars-body td:first-child").all_inner_texts(),
                    page.locator("#vars-body td:last-child").all_inner_texts()))
    assert rows == trace["steps"][i]["locals"]
    changed = page.locator("#vars-body tr.is-changed td:first-child").all_inner_texts()
    before, after = trace["steps"][i - 1]["locals"], trace["steps"][i]["locals"]
    assert set(changed) == {k for k in after if before.get(k) != after[k]}
    assert "a" in changed  # a, b = b, a + b
    assert "in fibonacci()" in page.inner_text("#vars-scope")


def test_recursion_shows_call_stack_and_return_value(page):
    load_example(page, "factorial")
    trace = run_code(CODE["factorial"])
    deepest = max(range(len(trace["steps"])), key=lambda k: trace["steps"][k]["depth"])
    go_to_step(page, deepest)
    assert page.inner_text("#call-stack") == "Call stack: main → " + " → ".join(["factorial()"] * 5)
    ret = next(k for k, s in enumerate(trace["steps"]) if s["event"] == "return" and s["return_value"] == "120")
    go_to_step(page, ret)
    assert page.inner_text("#vars-body .return-value") == "returns\t120"


def test_clicking_a_node_jumps_to_when_it_runs(page):
    load_example(page, "fibonacci")
    graph, trace = build_graph(CODE["fibonacci"]), run_code(CODE["fibonacci"])
    ret_node = next(n for n in graph["nodes"] if n["label"] == "return a")
    page.click(f'.node[data-id="{ret_node["id"]}"]')
    expected = next(k for k, s in enumerate(trace["steps"]) if node_for_step(graph, s) == ret_node["id"])
    assert step_label(page) == f"Step {expected + 1} of {len(trace['steps'])}"
    assert page.locator("#gutter .is-active").inner_text() == "7"

    # clicking the loop node again walks through its iterations
    loop = next(n for n in graph["nodes"] if n["type"] == "loop")
    hits = [k for k, s in enumerate(trace["steps"]) if node_for_step(graph, s) == loop["id"]]
    page.click(f'.node[data-id="{loop["id"]}"]')
    first = int(step_label(page).split()[1]) - 1
    page.click(f'.node[data-id="{loop["id"]}"]')
    second = int(step_label(page).split()[1]) - 1
    assert first in hits and second in hits and second != first


def test_node_that_never_ran_explains_why(page):
    visualize(page, "x = 1\nif x > 5:\n    print('big')\nprint('done')\n")
    page.wait_for_selector(".flowchart .node")
    page.click('.node:has-text("print(\'big\')")')
    assert "never ran" in page.inner_text("#message")


def test_keyboard_controls(page):
    load_example(page, "factorial")
    page.locator(".chart").click(position={"x": 5, "y": 5})  # focus away from the editor
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert step_label(page).startswith("Step 3 ")
    page.keyboard.press("ArrowLeft")
    assert step_label(page).startswith("Step 2 ")
    page.keyboard.press("End")
    assert page.is_disabled("#btn-forward")
    # typing in the editor must not move playback
    page.click("#code")
    page.keyboard.press("ArrowLeft")
    assert page.is_disabled("#btn-forward")


def test_play_runs_to_the_end_and_speed_matters(page):
    load_example(page, "factorial")
    total = len(run_code(CODE["factorial"])["steps"])
    page.eval_on_selector("#speed-slider", "el => { el.value = 4; el.dispatchEvent(new Event('input')); }")
    assert page.inner_text("#speed-label") == "4×"
    page.click("#btn-play")
    assert page.get_attribute("#btn-play", "aria-label") == "Pause"
    # 25 steps at 0.7 s / 4 ≈ 4.4 s; at 1× it would take ~17 s
    page.wait_for_function(f"document.querySelector('#step-label').textContent === 'Step {total} of {total}'",
                           timeout=8000)
    assert page.get_attribute("#btn-play", "aria-label") == "Play"


def test_runtime_error_marks_the_failing_node(page):
    visualize(page, "values = [1, 2, 0]\nfor v in values:\n    print(10 / v)\n")
    page.wait_for_selector(".flowchart .node")
    page.click("#btn-last")
    assert page.locator(".node.is-error").count() == 1
    assert page.locator("#gutter .is-error").inner_text() == "3"
    assert "ZeroDivisionError" in page.inner_text("#message")
