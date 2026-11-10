#!/usr/bin/env python3
"""Run Code Mirror's examples (or your own .py files) through the whole backend pipeline.

For each program it builds the graph, runs the tracer, and checks that the two fit
together. It is the quick "is the backend healthy?" check.

Usage (from the project root):
    python .claude/skills/code-mirror-testing/scripts/check_pipeline.py              # all built-in examples
    python .claude/skills/code-mirror-testing/scripts/check_pipeline.py my_prog.py   # your own file(s)
    python .claude/skills/code-mirror-testing/scripts/check_pipeline.py -v           # also print every step
    python .claude/skills/code-mirror-testing/scripts/check_pipeline.py --leaks      # allowlist leak check
    python .claude/skills/code-mirror-testing/scripts/check_pipeline.py --expect-error fails.py
        # for programs that are SUPPOSED to raise (e.g. a failing assert): the error is
        # printed but not counted as a failure; the step->node join is still checked

Exit code 0 = all checks passed, 1 = something failed.
It only reads files you name and runs code through Code Mirror's own sandboxed runner.
"""

import argparse
import importlib
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))  # run from the project root so `mirror` is importable

try:
    from mirror.examples import EXAMPLES
    from mirror.graph_builder import build_graph
    from mirror.runner import run_code
    from mirror.tracer import ALLOWED_MODULES
except ImportError:
    sys.exit("Run this from the Code Mirror project root (the folder that contains mirror/).")


def node_for_step(graph, step):
    """Same join as the frontend: call -> start, return -> end, line -> line_map."""
    func = graph["functions"].get(step["func"])
    if step["event"] == "call":
        return func and func["start"]
    if step["event"] == "return":
        return func and func["end"]
    return graph["line_map"].get(f'{step["func"]}:{step["line"]}')


def check_program(name, code, verbose, expect_error=False):
    problems = []
    try:
        graph = build_graph(code)
    except SyntaxError as e:
        return [f"syntax error on line {e.lineno}: {e.msg}"], None, None

    ids = {n["id"] for n in graph["nodes"]}
    for e in graph["edges"]:
        if e["from"] not in ids or e["to"] not in ids:
            problems.append(f"edge points at a missing node: {e}")
    for lane_index, lane in enumerate(graph["lanes"]):
        rows = sorted(n["row"] for n in graph["nodes"] if n["lane"] == lane_index)
        if rows != list(range(len(rows))):
            problems.append(f"lane {lane['func']} has gaps in its rows: {rows}")

    trace = run_code(code)
    if trace["error"] and not expect_error:
        problems.append(f"trace error: {trace['error']}")
    elif trace["error"]:
        print(f"    (expected error: {trace['error']['message']} on line {trace['error']['line']})")
    elif expect_error:
        problems.append("expected the program to raise an error, but it finished normally")
    unmapped = [s for s in trace["steps"] if node_for_step(graph, s) is None]
    if unmapped:
        problems.append(f"{len(unmapped)} of {len(trace['steps'])} steps have no node (listed below)")
    for s in unmapped[:20]:
        problems.append(f"step {s['i']} ({s['event']} {s['func']} line {s['line']}) has no node")
    if len(unmapped) > 20:
        problems.append(f"... and {len(unmapped) - 20} more (use -v to see every step)")

    if verbose:
        by_id = {n["id"]: n for n in graph["nodes"]}
        for s in trace["steps"]:
            nid = node_for_step(graph, s)
            label = by_id[nid]["label"] if nid else "—"
            ret = f"  -> {s['return_value']}" if "return_value" in s else ""
            print(f"    {s['i']:>3} {s['event']:<6} {'  ' * s['depth']}{label:<36} {s['locals']}{ret}")
    return problems, graph, trace


def leak_check():
    """Allowed modules must not expose other (non-allowed) modules as public attributes
    to user code. The tracer's ModuleProxy filters these out; this lists what it has to filter."""
    print("Public module attributes that ModuleProxy must hide:")
    for m in sorted(ALLOWED_MODULES):
        mod = importlib.import_module(m)
        hidden = [a for a in dir(mod) if not a.startswith("_")
                  and isinstance(getattr(mod, a), types.ModuleType)
                  and getattr(mod, a).__name__.split(".")[0] not in ALLOWED_MODULES]
        if hidden:
            print(f"  {m}: {', '.join(hidden)}")
    trace = run_code("import fractions\nx = fractions.sys\n")
    ok = trace["error"] and "has no attribute 'sys'" in trace["error"]["message"]
    print("  proxy blocks fractions.sys:", "OK" if ok else "FAILED")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="Python files to check (default: built-in examples)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every trace step")
    parser.add_argument("--leaks", action="store_true", help="run the module allowlist leak check")
    parser.add_argument("--expect-error", action="store_true",
                        help="the program is meant to raise; check the join but don't fail on the error")
    args = parser.parse_args()

    if args.leaks:
        sys.exit(0 if leak_check() else 1)

    programs = [(p, Path(p).read_text()) for p in args.files] or [(e["id"], e["code"]) for e in EXAMPLES]
    failed = 0
    print(f"{'program':<16} {'nodes':>5} {'edges':>5} {'lanes':>5} {'steps':>5}  result")
    for name, code in programs:
        if args.verbose:
            print(f"--- {name}")
        problems, graph, trace = check_program(name, code, args.verbose, args.expect_error)
        if graph is None:
            print(f"{name:<16} {'-':>5} {'-':>5} {'-':>5} {'-':>5}  FAIL")
        else:
            steps = f"{len(trace['steps'])}{'+' if trace['truncated'] else ''}"
            print(f"{name:<16} {len(graph['nodes']):>5} {len(graph['edges']):>5} {len(graph['lanes']):>5} "
                  f"{steps:>5}  {'ok' if not problems else 'FAIL'}   stdout={trace['stdout'][:40]!r}")
        for p in problems:
            print(f"    ! {p}")
        failed += bool(problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
