"""Stage 1 tests: AST -> graph JSON. Run with:  python -m pytest tests/test_graph.py"""

import json

import pytest

from mirror.examples import EXAMPLES
from mirror.graph_builder import build_graph

CODE = {ex["id"]: ex["code"] for ex in EXAMPLES}
NODE_TYPES = {"start", "statement", "decision", "loop", "call", "return", "end"}


def edges_from(graph, node_id):
    return [e for e in graph["edges"] if e["from"] == node_id]


def node_by_label(graph, prefix):
    matches = [n for n in graph["nodes"] if n["label"].startswith(prefix)]
    assert matches, f"no node starting with {prefix!r}"
    return matches[0]


@pytest.mark.parametrize("example_id", CODE)
def test_every_example_builds_valid_graph(example_id):
    graph = build_graph(CODE[example_id])
    json.dumps(graph)  # must be JSON-serialisable for Flask
    ids = {n["id"] for n in graph["nodes"]}

    for n in graph["nodes"]:
        assert n["type"] in NODE_TYPES
    for e in graph["edges"]:
        assert e["from"] in ids and e["to"] in ids
        assert e["kind"] in {"normal", "back", "call"}
    # every line_map entry points at a real node
    assert set(graph["line_map"].values()) <= ids
    # each lane has exactly one start and one end
    for lane_index, lane in enumerate(graph["lanes"]):
        lane_nodes = [n for n in graph["nodes"] if n["lane"] == lane_index]
        assert [n["type"] for n in lane_nodes].count("start") == 1
        assert [n["type"] for n in lane_nodes].count("end") == 1
        rows = sorted(n["row"] for n in lane_nodes)
        assert rows == list(range(len(rows))), "rows inside a lane are 0..N-1 with no gaps"


def test_fibonacci_while_loop():
    g = build_graph(CODE["fibonacci"])
    loop = node_by_label(g, "while count < n")
    assert loop["type"] == "loop"
    labels = sorted(e["label"] for e in edges_from(g, loop["id"]))
    assert labels == ["False", "True"]
    # the last line of the body jumps back up to the loop
    body_end = node_by_label(g, "count += 1")
    assert edges_from(g, body_end["id"]) == [{"from": body_end["id"], "to": loop["id"], "label": None, "kind": "back"}]
    # the call in the main program links to the function's start
    call = node_by_label(g, "result = fibonacci(8)")
    assert call["type"] == "call"
    start = g["functions"]["fibonacci"]["start"]
    assert {"from": call["id"], "to": start, "label": None, "kind": "call"} in g["edges"]


def test_bubble_sort_break_leaves_the_outer_loop():
    g = build_graph(CODE["bubble_sort"])
    brk = node_by_label(g, "break")
    ret = node_by_label(g, "return items")
    assert [e["to"] for e in edges_from(g, brk["id"])] == [ret["id"]]
    # the inner `if` has a False edge straight back to the inner loop
    inner_if = node_by_label(g, "if items[j]")
    inner_loop = node_by_label(g, "for j in")
    assert {"from": inner_if["id"], "to": inner_loop["id"], "label": "False", "kind": "back"} in g["edges"]
    # nesting depth matches indentation
    assert inner_loop["col"] == 1 and inner_if["col"] == 2


def test_factorial_recursion_and_returns():
    g = build_graph(CODE["factorial"])
    returns = [n for n in g["nodes"] if n["type"] == "return"]
    assert len(returns) == 2
    end = g["functions"]["factorial"]["end"]
    for r in returns:
        assert any(e["to"] == end for e in edges_from(g, r["id"]))
    recursive = node_by_label(g, "return n * factorial")
    assert recursive["calls"] == ["factorial"]


def test_fizzbuzz_elif_chain():
    g = build_graph(CODE["fizzbuzz"])
    decisions = [n for n in g["nodes"] if n["type"] == "decision"]
    assert [d["label"].split()[0] for d in decisions] == ["if", "elif", "elif"]
    assert {d["col"] for d in decisions} == {1}, "elif is drawn at the same depth as its if"
    # the else branch hangs off the last elif's False edge
    last = decisions[-1]
    else_target = [e["to"] for e in edges_from(g, last["id"]) if e["label"] == "False"][0]
    assert g["nodes"][int(else_target[1:])]["label"] == "print(n)"


def test_line_map_uses_function_and_line():
    g = build_graph(CODE["factorial"])
    # line 2 inside factorial is the `if`; line 6 in the main program is the call
    assert g["nodes"][int(g["line_map"]["factorial:2"][1:])]["type"] == "decision"
    assert g["nodes"][int(g["line_map"]["<module>:6"][1:])]["type"] == "call"


def test_methods_and_nested_functions_get_their_own_lanes():
    code = (
        "class Counter:\n"
        "    def add(self, x):\n"
        "        return x + 1\n"
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n"
    )
    g = build_graph(code)
    # qualnames match Python's own co_qualname, which is what the tracer reports
    assert [lane["func"] for lane in g["lanes"]] == ["<module>", "Counter.add", "outer", "outer.<locals>.inner"]
    # the class body itself has no lane, but is registered so its steps find the class box
    class_box = node_by_label(g, "class Counter")
    assert g["functions"]["Counter"] == {"start": class_box["id"], "end": class_box["id"], "lane": 0}
    assert g["line_map"]["Counter:2"] == class_box["id"]  # `def add` runs inside the class body


def test_multiline_statement_maps_every_line():
    g = build_graph("total = (1 +\n         2)\n")
    assert g["line_map"]["<module>:1"] == g["line_map"]["<module>:2"]


def test_with_header_is_in_line_map():
    # Regression: the `with` line was left out of line_map, so it never lit up in playback.
    g = build_graph("with open('f') as fh:\n    x = 1\n")
    node = node_by_label(g, "with open('f') as fh")
    assert g["line_map"]["<module>:1"] == node["id"]
    assert g["line_map"]["<module>:2"] != node["id"]


def test_syntax_error_is_raised():
    with pytest.raises(SyntaxError):
        build_graph("if x\n    pass\n")


def test_assert_is_a_decision_whose_false_edge_ends_the_lane():
    code = (
        "def half(n):\n"
        "    assert n % 2 == 0, 'odd'\n"
        "    return n // 2\n"
        "x = half(4)\n"
        "assert x == 2\n"
        "print(x)\n"
    )
    g = build_graph(code)
    for label, func, after in [("assert x == 2", "<module>", "print(x)"), ("assert n % 2 == 0", "half", "return n // 2")]:
        node = node_by_label(g, label)
        assert node["type"] == "decision"
        assert node["func"] == func
        assert g["line_map"][f'{func}:{node["line"]}'] == node["id"]
        out = {e["label"]: e for e in edges_from(g, node["id"])}
        assert set(out) == {"True", "False"}
        assert out["True"]["to"] == node_by_label(g, after)["id"]
        assert out["True"]["kind"] == "normal"
        assert out["False"]["to"] == g["functions"][func]["end"]
        assert out["False"]["kind"] == "normal"


def test_assert_inside_loop_and_multiline_assert():
    g = build_graph("for i in range(3):\n    assert (i <\n            5)\n")
    node = node_by_label(g, "assert i < 5")
    assert node["col"] == 1
    assert g["line_map"]["<module>:2"] == g["line_map"]["<module>:3"] == node["id"]
    loop = node_by_label(g, "for i in")
    out = {e["label"]: e for e in edges_from(g, node["id"])}
    assert out["True"]["to"] == loop["id"] and out["True"]["kind"] == "back"
    assert out["False"]["to"] == g["functions"]["<module>"]["end"]
