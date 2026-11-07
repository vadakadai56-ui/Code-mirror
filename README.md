# Code Mirror

Paste Python code and watch it run as an animated flowchart.

Code Mirror reads your program, draws it as a flowchart that has the same shape as
your code, then runs it and replays every step: the current box lights up, a dot
travels along the arrow that was taken, and the variables panel shows what changed.

- **Left:** a code editor with line numbers, plus the program's output.
- **Right:** the flowchart, playback controls (play, pause, step, speed) and the variables.
- Click any box to jump to the moment that line runs. Click a loop again to see its next pass.
- Built-in examples: Fibonacci (while loop), bubble sort (nested for loops),
  factorial (recursion) and FizzBuzz (if / elif / else).

## Run it

You need **Python 3.11 or newer**.

```bash
git clone <this repository>
cd Code-mirror
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

Animations use the [Motion](https://motion.dev) library, which the page loads from
cdn.jsdelivr.net. Without internet access everything still works; it just switches
instantly instead of animating.

### Keyboard

| Key | Action |
|---|---|
| Ctrl+Enter (⌘+Enter) | Visualize |
| Space | Play / pause |
| ← / → | Step back / forward |
| Home / End | First / last step |
| Tab then Enter on a box | Jump to that step |
| Esc then Tab | Leave the code editor |

You can link straight to an example: `http://127.0.0.1:5000/?example=factorial`.

## What it can show

`if` / `elif` / `else`, `match` / `case` (each case is tried in order, with guards),
`for` and `while` loops (including `break`, `continue` and `else:`), functions and calls, recursion (with the call stack), `return`, `assert`,
classes and methods, `try` / `except` and `with`.

## Limits and safety

Your code runs in a separate Python process with guard rails:

- It's stopped after **3 seconds**, and the replay shows at most **500 steps**.
  A loop that never ends stops at step 500, and you can still replay what happened.
- `open`, `eval`, `exec`, `input`, `getattr` and similar are switched off.
- Only these modules can be imported: `math`, `random`, `string`, `itertools`,
  `functools`, `collections`, `heapq`, `bisect`, `statistics`, `fractions`, `operator`,
  `copy`, `re`, `time`. Importing `os`, `sys`, `subprocess` and others is blocked.
- Attribute names starting with `_` (like `self._count` or `super().__init__()`) are
  blocked, because they can reach Python's internals. Use names without the underscore.
- Memory, CPU time and file writing are limited (on Linux and macOS).
- The server only listens on `127.0.0.1`, so other computers can't reach it.

These limits make mistakes safe for a **local learning tool**. They are not a
security sandbox for running untrusted code from other people, so don't put this
server on the internet.

## How it works

```
your code ──► mirror/graph_builder.py  (reads the code with `ast`, never runs it) ──► graph JSON ─┐
          └─► mirror/runner.py ─► separate process: mirror/tracer.py (sys.settrace) ─► trace JSON ─┴─► browser
```

| File | What it does |
|---|---|
| `app.py` | Flask server: the page, `/api/examples`, `/api/visualize` |
| `mirror/graph_builder.py` | Python code → flowchart nodes and edges |
| `mirror/tracer.py` | runs inside the separate process; records each step and its variables |
| `mirror/runner.py` | starts the tracer process, enforces the time limit, explains errors |
| `mirror/examples.py` | the built-in examples |
| `static/flowchart.js` | draws the flowchart as SVG |
| `static/playback.js` | steps through the trace, variables panel, clicking boxes |
| `static/motion.js` | **all** animations (Motion library) |
| `static/editor.js`, `static/app.js` | the editor and the wiring between everything |

The exact JSON formats are documented in `.claude/skills/code-mirror-architecture/SKILL.md`.

## Tests

```bash
python -m pytest tests/test_graph.py tests/test_tracer.py tests/test_api.py   # backend, a few seconds
python .claude/skills/code-mirror-testing/scripts/check_pipeline.py          # examples end to end

# browser tests (Playwright + Chromium), about a minute
pip install playwright
python -m playwright install chromium
python -m pytest tests/e2e
```

## Claude Code skills in this project

`.claude/skills/` holds skills that Claude Code loads when working on this repository:

| Skill | Source | Used for |
|---|---|---|
| `code-mirror-architecture` | this project | graph/trace formats, module boundaries |
| `code-mirror-motion` | this project | animation conventions |
| `code-mirror-testing` | this project | how to test (includes `check_pipeline.py`) |
| `skill-creator` | anthropics/skills @2c5958e | creating and improving skills |
| `webapp-testing` | anthropics/skills @2c5958e | Playwright testing approach |
| `frontend-design` | anthropics/skills @2c5958e | visual design guidance |
| `web-design-guidelines` | vercel-labs/agent-skills @1a2c79d | UI/accessibility review; changed to read a pinned local `guidelines.md` instead of fetching rules from the network |
