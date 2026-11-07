---
name: code-mirror-testing
description: How to test the Code Mirror app - running the example snippets (fibonacci, bubble sort, factorial, FizzBuzz) through the AST-graph and tracer pipeline, running pytest, and checking the frontend in a real browser with Playwright. Use this skill whenever you have changed Code Mirror code and need to verify it, when an example looks wrong in the flowchart or playback, when adding a new example or a new supported Python feature, when touching the sandbox allowlists, or when asked "does it still work?", even if the user does not say "test".
---

# Testing Code Mirror

Run from the project root. There are three levels; use the cheapest one that covers
your change, and always finish with level 1 + 2 before committing.

Before you debug, run `git status` and `git diff`. A bug can come from an uncommitted
local edit rather than from the committed code. That's worth knowing before you start
reading the code.

## Level 1: pipeline check (seconds)

```bash
python .claude/skills/code-mirror-testing/scripts/check_pipeline.py        # all examples
python .claude/skills/code-mirror-testing/scripts/check_pipeline.py -v     # + every step
python .claude/skills/code-mirror-testing/scripts/check_pipeline.py prog.py # your own file
```

For each program this builds the graph, runs the real sandboxed tracer, and checks:
- edges point at real nodes, and rows in each lane are 0..N-1;
- the trace has no error;
- **every trace step maps to a node** (the frontend's join; see code-mirror-architecture).
  An unmapped step means a node never lights up during playback. That's the most
  common bug when adding a new statement type.

Expected output today (update this table when examples change):

| program | nodes | edges | lanes | steps | stdout |
|---|---|---|---|---|---|
| fibonacci | 13 | 13 | 2 | 35 | `fibonacci(8) = 21` |
| bubble_sort | 17 | 20 | 2 | 56 | `[1, 2, 5, 6, 9]` |
| factorial | 10 | 11 | 2 | 25 | `5! = 120` |
| fizzbuzz | 10 | 13 | 1 | 72 | `1 2 Fizz 4 Buzz …` |

Use `-v` when an example "looks wrong": it prints each step indented by call depth,
with the node label it maps to (`—` = no node) and the variables at that moment.
Without `-v` the script prints the total number of unmapped steps and the first 20, so
always check the count: the step you care about may not be among the first 20.

For a program that is *meant* to fail (for example a failing `assert`), add
`--expect-error`. The error is printed but doesn't count as a failure, and the
step→node join is still checked.

If you changed `ALLOWED_MODULES` or the builtins in `tracer.py`, also run
`check_pipeline.py --leaks`.

## Level 2: pytest (about 4 s)

```bash
python -m pytest -q                 # everything
python -m pytest tests/test_graph.py   # stage 1: AST -> graph
python -m pytest tests/test_tracer.py  # stage 2: tracer, limits, sandbox
python -m pytest tests/test_api.py     # Flask routes
```

The tracer tests include intentionally slow cases (timeout ≈ 3 s), so the run takes a few seconds.
When you add behaviour, add a test next to the closest existing one. Graph tests assert
on node labels and edge labels/kinds, not on node ids (ids shift when code changes).

## Level 3: browser tests (Playwright)

For frontend changes (drawing, playback, motion). Use the webapp-testing skill's
approach: start the server, wait for `networkidle`, then interact. The tests live in
`tests/e2e/`. If a frontend feature has no browser test yet, add one there instead of
skipping this level.

```bash
python .claude/skills/webapp-testing/scripts/with_server.py \
  --server "python app.py" --port 5000 -- python -m pytest tests/e2e -q
```

Things that are specific to Code Mirror:
- **The CDN may be blocked** (the cloud dev container blocks cdn.jsdelivr.net). The e2e
  fixture serves a local ESM bundle of the same pinned Motion version with
  `page.route("https://cdn.jsdelivr.net/npm/motion@*/+esm", ...)`. Don't edit the
  app's import URL to make tests pass.
- Run playback tests twice: normally and with `reduced_motion="reduce"`. The final
  highlighted node and variables must be the same.
- Check state through the DOM (the active node's class, the variables panel text, the
  highlighted editor line), not through screenshots alone. Take screenshots at
  `device_scale_factor=1` when they are only for your own inspection.
- Pass `--trace off` to Playwright unless you are debugging a failure.

## What to report

Say which levels you ran, the exact commands, and the pass/fail counts. If something
was skipped (for example, browser tests because the server couldn't start), say so
plainly instead of implying it passed.
