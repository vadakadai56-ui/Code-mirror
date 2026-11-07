---
name: code-mirror-architecture
description: Data contracts and module boundaries for the Code Mirror app (Python code to animated flowchart). Use this skill before changing or debugging anything that produces or consumes the graph JSON or the trace JSON - mirror/graph_builder.py, mirror/tracer.py, mirror/runner.py, app.py, or frontend code that reads nodes, edges, line_map or trace steps. This includes supporting a new Python statement, adding a field to trace steps, fixing a node that never lights up during playback, or changing node types or edge kinds, even when the request does not say "architecture".
---

# Code Mirror architecture

Code Mirror turns pasted Python into a flowchart and replays its execution.
Two independent halves produce data, and the browser joins them:

```
code ──► graph_builder.py (reads AST, never runs code) ──► graph JSON ─┐
     └─► runner.py ─► subprocess: tracer.py (sys.settrace) ─► trace JSON ─┴─► app.py ─► browser
```

## The separation rule (and why)

- **graph_builder.py never runs code; tracer.py never knows about nodes.**
  The graph must still be drawable when the code crashes, times out or is blocked,
  and the tracer runs in a locked-down process that shouldn't import project code.
- **Python never computes pixels; drawing JS never runs or parses Python.**
  The builder only gives layout *hints* (`lane`, `row`, `col`).
- The only meeting point is the join described below. If a change seems to need the
  tracer to know node ids (or the builder to know runtime values), change the join
  tables instead.
- `tracer.py` is started with `python -I -S`, so it can't import anything from
  `mirror/`. It must stay standalone (stdlib only) and importable without side
  effects, because `runner.py` imports `check_code` from it.

## Graph JSON (from `build_graph(source)`)

```json
{
  "nodes": [{"id": "n9", "type": "loop", "label": "while count < n",
             "line": 4, "end_line": 4, "func": "fibonacci",
             "lane": 1, "row": 3, "col": 0, "calls": []}],
  "edges": [{"from": "n9", "to": "n10", "label": "True", "kind": "normal"}],
  "lanes": [{"func": "<module>", "title": "Main program"}, {"func": "fibonacci", "title": "fibonacci()"}],
  "functions": {"fibonacci": {"start": "n5", "end": "n6", "lane": 1}},
  "line_map": {"fibonacci:4": "n9"}
}
```

| Field | Meaning |
|---|---|
| `type` | `start`, `statement`, `decision` (if/elif/assert), `loop` (for/while), `call` (statement that calls a user function), `return`, `end` |
| `func` | Python's `co_qualname` for the scope: `<module>`, `fib`, `Stack.push`, `outer.<locals>.inner` |
| `lane` | one column per scope; lane 0 is the main program |
| `row` | order inside the lane, 0..N-1 with no gaps; `end` is always last |
| `col` | indentation depth, so the chart has the same shape as the code |
| `calls` | names of user-defined functions called on this line |
| edge `label` | `True`/`False` (if, while, assert), `next`/`done` (for), `error` (try→except), or `null` |
| edge `kind` | `normal` (to a later row), `back` (to the same or an earlier row, e.g. loop repeat), `call` (dashed, to another lane's start) |

Rules that tests rely on: `elif` sits at the same `col` as its `if`; `break` goes to
whatever follows the loop; `continue` and the end of a loop body get `back` edges to
the loop node; `return` connects to its lane's `end` node.
`assert cond` is a `decision` labelled `assert <cond>` (the message is left out): its
`True` edge goes to the next statement, its `False` edge goes to its lane's `end` node
(the program stops there with `AssertionError`, which the trace reports as a `runtime` error).

## Trace JSON (from `run_code(source)`)

```json
{
  "steps": [{"i": 3, "event": "call", "line": 1, "func": "fibonacci", "depth": 1,
             "stack": ["<module>", "fibonacci"], "locals": {"n": "8"},
             "stdout_len": 0, "return_value": "21"}],
  "stdout": "fibonacci(8) = 21\n",
  "truncated": false,
  "error": null
}
```

- `event`: `call` (function started), `line` (about to run this line), `return` (function finished; has `return_value`).
- `locals` are short `repr` strings, recorded *before* the line runs. Functions,
  classes, modules and `__dunder__` names are left out.
- `stdout_len`: how much of `stdout` had been printed at this step (`stdout[:stdout_len]`).
- At most 500 steps; after that `truncated` is `true` and `error` is `null`.
- `error` is `null` or `{"kind", "message", "line"}`, where kind is one of
  `syntax`, `blocked`, `runtime`, `timeout`, `crash`. When kind is `syntax`, `/api/visualize` returns `graph: null`.

## Frontend modules (static/)

| File | Job | Must not |
|---|---|---|
| `app.js` | wiring: examples menu, Visualize, error/output panels, keyboard, speed | draw SVG or animate |
| `editor.js` | textarea, line numbers, line highlight | know about graphs |
| `flowchart.js` | `drawFlowchart(container, graph)` → handles `{svg, nodes, edges, dot, edgeBetween}`; layout from `lane/row/col` | animate, or know about traces |
| `playback.js` | step state, the join (`nodeForStep`), variables panel, node clicks | call Motion directly (it calls `effects`) |
| `motion.js` | every animation (see code-mirror-motion) | change what is shown, only how it moves |

## The join: step → node

`static/playback.js::nodeForStep` does exactly this, and `tests/test_tracer.py::node_for_step`
mirrors it in Python (the e2e playback tests compare the two):

```
call   → graph.functions[step.func].start
return → graph.functions[step.func].end
line   → graph.line_map[`${step.func}:${step.line}`]   (may be undefined → highlight nothing)
```

`line_map` covers every source line a node spans. For compound statements that means
the header lines only (e.g. a multi-line `if (...)` condition).

Join rules that are easy to break:
- Only `def` start nodes use `map_lines=False` in `_add()`, because they are reached by
  `call` events, not `line` events. Every other node must put its header lines in
  `line_map`. Some headers run more than once: `with` runs on entry *and* on exit,
  and `for`/`while` run on every pass.
- A class body runs as its own scope named after the class (e.g. `Timer`). It has no
  lane. Instead, `functions["Timer"]` points start and end at the `class Timer` box,
  and `line_map["Timer:<line>"]` covers the whole class, so its steps light up that box.
- A step that legitimately has no node (for example inside a `match` case body,
  which is drawn as one box) highlights nothing. That's allowed, but the pipeline check
  reports it, so add a node or a mapping when you add a statement type.

## Safety layers (tracer.py / runner.py)

1. `check_code()`: import allowlist (`ALLOWED_MODULES`), no `__names__` except
   `__name__`, no attributes starting with `_`, no frame-walking attributes
   (`BLOCKED_ATTRS`). This runs in runner.py before a process starts, and again in the child.
2. A builtins allowlist. Disabled builtins raise `PermissionError` with a clear message.
3. Imports return a `ModuleProxy` with only public, non-module attributes, because
   modules like `fractions.sys` would otherwise leak `sys`.
4. rlimits for memory, CPU and file size; a 3 s wall-clock kill; an empty environment;
   the cwd set to the temp dir.
5. Flask binds to `127.0.0.1` only.

When you add a builtin or module to an allowlist, run the "allowed modules leak other
modules" check in the code-mirror-testing skill.

## Changing a format: checklist

1. Change the producer (`graph_builder.py` or `tracer.py`).
2. Update the tests in `tests/test_graph.py` / `tests/test_tracer.py`, including `node_for_step` if the join changes.
3. Update the frontend consumer.
4. **Update this SKILL.md** (formats, tables, join). Stale docs here are worse than none.
5. Run the full pipeline check from the code-mirror-testing skill.
