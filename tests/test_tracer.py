"""Stage 2 tests: running code in the subprocess and recording a trace.

Run with:  python -m pytest tests/test_tracer.py
"""

import pytest

from mirror.examples import EXAMPLES
from mirror.graph_builder import build_graph
from mirror.runner import run_code

CODE = {ex["id"]: ex["code"] for ex in EXAMPLES}
EXPECTED_STDOUT = {
    "fibonacci": "fibonacci(8) = 21\n",
    "bubble_sort": "[1, 2, 5, 6, 9]\n",
    "factorial": "5! = 120\n",
    "fizzbuzz": "1\n2\nFizz\n4\nBuzz\nFizz\n7\n8\nFizz\nBuzz\n11\nFizz\n13\n14\nFizzBuzz\n",
}


def node_for_step(graph, step):
    """The same lookup the frontend does: call -> start, return -> end, line -> line_map."""
    func = graph["functions"].get(step["func"])
    if step["event"] == "call":
        return func and func["start"]
    if step["event"] == "return":
        return func and func["end"]
    return graph["line_map"].get(f'{step["func"]}:{step["line"]}')


# ------------------------------------------------------------------ examples
@pytest.mark.parametrize("example_id", CODE)
def test_examples_run_and_every_step_maps_to_a_node(example_id):
    trace = run_code(CODE[example_id])
    assert trace["error"] is None
    assert trace["truncated"] is False
    assert trace["stdout"] == EXPECTED_STDOUT[example_id]
    assert 0 < len(trace["steps"]) <= 500
    assert [s["i"] for s in trace["steps"]] == list(range(len(trace["steps"])))

    # Joining tracer output with the graph is how the frontend highlights nodes.
    graph = build_graph(CODE[example_id])
    unmapped = [s for s in trace["steps"] if node_for_step(graph, s) is None]
    assert unmapped == []


def test_fibonacci_final_values():
    steps = run_code(CODE["fibonacci"])["steps"]
    ret = [s for s in steps if s["event"] == "return" and s["func"] == "fibonacci"][0]
    assert ret["return_value"] == "21"
    assert ret["locals"]["count"] == "8"


def test_factorial_recursion_depth_and_stack():
    steps = run_code(CODE["factorial"])["steps"]
    calls = [s for s in steps if s["event"] == "call" and s["func"] == "factorial"]
    assert [s["locals"]["n"] for s in calls] == ["5", "4", "3", "2", "1"]
    deepest = max(steps, key=lambda s: s["depth"])
    assert deepest["depth"] == 5
    assert deepest["stack"] == ["<module>"] + ["factorial"] * 5
    returns = [s["return_value"] for s in steps if s["event"] == "return" and s["func"] == "factorial"]
    assert returns == ["1", "2", "6", "24", "120"]


def test_stdout_len_grows_as_output_is_printed():
    trace = run_code(CODE["fizzbuzz"])
    lengths = [s["stdout_len"] for s in trace["steps"]]
    assert lengths == sorted(lengths)
    assert lengths[-1] == len(trace["stdout"])


def test_functions_and_modules_are_hidden_from_variables():
    steps = run_code("import math\ndef f():\n    pass\nx = 1\n")["steps"]
    assert steps[-1]["locals"] == {"x": "1"}


def test_assert_steps_map_to_the_assert_node():
    code = "def half(n):\n    assert n % 2 == 0, 'odd'\n    return n // 2\nx = half(4)\nassert x == 2\ny = half(3)\n"
    graph = build_graph(code)
    trace = run_code(code)
    assert trace["error"] == {"kind": "runtime", "message": "AssertionError: odd", "line": 2}
    assert [s for s in trace["steps"] if node_for_step(graph, s) is None] == []
    assert_nodes = {n["id"] for n in graph["nodes"] if n["label"].startswith("assert")}
    hit = [node_for_step(graph, s) for s in trace["steps"] if s["event"] == "line"]
    assert hit.count(graph["line_map"]["half:2"]) == 2  # passed once, failed once
    assert graph["line_map"]["<module>:5"] in hit
    assert set(graph["line_map"][k] for k in ("half:2", "<module>:5")) == assert_nodes


def test_with_statement_lines_map_to_nodes():
    # Regression: the `with` header line (run on enter and again on exit) had no node.
    code = (
        "class Timer:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, *args):\n"
        "        return False\n"
        "\n"
        "with Timer() as t:\n"
        "    x = 1\n"
        "print(x)\n"
    )
    graph = build_graph(code)
    trace = run_code(code)
    assert trace["error"] is None
    with_steps = [s for s in trace["steps"] if s["func"] == "<module>" and s["line"] == 7 and s["event"] == "line"]
    assert len(with_steps) == 2  # entering and leaving the block
    with_node = [n for n in graph["nodes"] if n["label"] == "with Timer() as t"][0]
    assert all(node_for_step(graph, s) == with_node["id"] for s in with_steps)


# -------------------------------------------------------------------- errors
def test_syntax_error():
    trace = run_code("for i in range(3)\n    print(i)\n")
    assert trace["error"]["kind"] == "syntax"
    assert trace["error"]["line"] == 1


def test_runtime_error_reports_line_and_keeps_steps():
    trace = run_code("x = 1\ny = 0\nz = x / y\n")
    assert trace["error"]["kind"] == "runtime"
    assert trace["error"]["message"].startswith("ZeroDivisionError")
    assert trace["error"]["line"] == 3
    assert trace["steps"], "the steps before the crash are still shown"


def test_infinite_loop_stops_at_500_steps():
    trace = run_code("n = 0\nwhile True:\n    n += 1\n")
    assert trace["truncated"] is True
    assert len(trace["steps"]) == 500
    assert trace["error"] is None


def test_step_limit_cannot_be_caught_by_user_code():
    code = "try:\n    while True:\n        pass\nexcept BaseException:\n    print('escaped')\n"
    trace = run_code(code)
    assert trace["truncated"] is True and "escaped" not in trace["stdout"]


def test_slow_single_line_hits_the_timeout():
    trace = run_code("total = sum(range(10 ** 12))\n")
    assert trace["error"]["kind"] == "timeout"


def test_huge_memory_use_is_stopped():
    trace = run_code("big = [0] * (10 ** 10)\n")
    assert trace["error"] is not None
    assert "MemoryError" in trace["error"]["message"] or trace["error"]["kind"] in ("crash", "timeout")


def test_print_output_is_capped():
    trace = run_code("print('x' * 100000)\n")
    assert len(trace["stdout"]) == 20_000


# -------------------------------------------------------------------- safety
@pytest.mark.parametrize(
    "code, fragment",
    [
        ("import os\n", "Importing 'os' is not allowed"),
        ("import sys\n", "Importing 'sys' is not allowed"),
        ("import subprocess\n", "Importing 'subprocess' is not allowed"),
        ("from os import path\n", "Importing 'os' is not allowed"),
        ("__import__('os')\n", "'__import__' is blocked"),
        ("x = ().__class__\n", "'.__class__' is blocked"),
        ("import random\nr = random._os\n", "'._os' is blocked"),
        ("def g():\n    yield 1\nf = g().gi_frame\n", "'.gi_frame' is blocked"),
    ],
)
def test_blocked_code_is_rejected_before_running(code, fragment):
    trace = run_code(code)
    assert trace["error"]["kind"] == "blocked"
    assert fragment in trace["error"]["message"]
    assert trace["steps"] == []


@pytest.mark.parametrize("name", ["open", "eval", "exec", "getattr", "input"])
def test_dangerous_builtins_are_disabled(name):
    trace = run_code(f"{name}('x')\n")
    assert trace["error"]["kind"] == "blocked"
    assert f"{name}() is disabled" in trace["error"]["message"]


def test_allowed_modules_do_not_leak_other_modules():
    # `fractions.sys` exists on the real module; the user only gets a filtered copy.
    trace = run_code("import fractions\nx = fractions.sys\n")
    assert trace["error"]["kind"] == "runtime"
    assert "has no attribute 'sys'" in trace["error"]["message"]


def test_allowed_imports_work():
    code = "import math\nfrom collections import Counter\nimport random\nprint(math.sqrt(16), Counter('aab')['a'])\n"
    trace = run_code(code)
    assert trace["error"] is None
    assert trace["stdout"] == "4.0 2\n"


def test_classes_and_methods_trace():
    code = "class Box:\n    def __init__(self, v):\n        self.v = v\n    def get(self):\n        return self.v\nb = Box(3)\nprint(b.get())\n"
    trace = run_code(code)
    assert trace["error"] is None and trace["stdout"] == "3\n"
    funcs = {s["func"] for s in trace["steps"]}
    assert {"Box.__init__", "Box.get"} <= funcs


def test_match_steps_map_to_case_nodes():
    code = (
        "def describe(value):\n"
        "    match value:\n"
        "        case 0:\n"
        "            return 'zero'\n"
        "        case [x, y]:\n"
        "            return 'pair'\n"
        "        case _:\n"
        "            return 'other'\n"
        "for v in [0, [1, 2], 7.5]:\n"
        "    print(describe(v))\n"
    )
    graph, trace = build_graph(code), run_code(code)
    assert trace["error"] is None and trace["stdout"] == "zero\npair\nother\n"
    assert all(node_for_step(graph, s) for s in trace["steps"])
    labels = {n["id"]: n["label"] for n in graph["nodes"]}
    visited = [labels[node_for_step(graph, s)] for s in trace["steps"] if s["func"] == "describe"]
    # for 7.5 every case is tried in order before `case _` matches
    assert visited[-6:] == ["match value", "case 0", "case [x, y]", "case _", "return 'other'", "end of describe()"]
