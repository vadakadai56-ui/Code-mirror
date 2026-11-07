// playback.js — steps through the trace and shows each step on the page.
//
// For every step it:
//   * finds the flowchart node for the step (the "join", see nodeForStep below)
//   * marks that node active and the edge we just travelled as taken
//   * highlights the matching line in the editor
//   * shows the variables, the call stack and the output printed so far
//
// It never animates anything itself. Movement is done by the `effects` object
// (motion.js in stage 5); without effects everything just switches instantly.

const BASE_STEP_SECONDS = 0.7; // time per step at 1× speed when playing

/** The step -> node join. Must match code-mirror-architecture's description. */
export function nodeForStep(graph, step) {
  const func = graph.functions[step.func];
  if (step.event === "call") return func ? func.start : null;
  if (step.event === "return") return func ? func.end : null;
  return graph.line_map[`${step.func}:${step.line}`] || null;
}

const NO_EFFECTS = {
  nodeEntered() {},
  travel() {},
  variablesChanged() {},
  stepSeconds: (seconds) => seconds,
  stop() {},
};

export function createPlayback({ chart, graph, trace, editor, ui, effects = NO_EFFECTS }) {
  const steps = trace.steps;
  const nodeIds = steps.map((s) => nodeForStep(graph, s));
  let index = -1;
  let timer = null;
  let activeId = null;
  let takenEdge = null;

  ui.slider.max = Math.max(0, steps.length - 1);
  ui.root.hidden = steps.length === 0;
  ui.variables.hidden = steps.length === 0;

  // ------------------------------------------------------------- show a step
  function show(newIndex, { travelled = false } = {}) {
    if (!steps.length) return;
    newIndex = Math.max(0, Math.min(steps.length - 1, newIndex));
    const previousIndex = index;
    index = newIndex;
    const step = steps[index];
    const nodeId = nodeIds[index];

    // Node highlight.
    const prevId = activeId;
    if (activeId) chart.nodes.get(activeId)?.el.classList.remove("is-active");
    activeId = nodeId;
    const node = nodeId ? chart.nodes.get(nodeId) : null;
    if (node) {
      node.el.classList.add("is-active", "is-visited");
      scrollIntoView(node.el);
    }

    // Edge we just walked along (only when moving forward one step).
    if (takenEdge) takenEdge.closest(".edge").classList.remove("is-taken");
    takenEdge = null;
    if (travelled && prevId && nodeId && prevId !== nodeId) {
      takenEdge = chart.edgeBetween(prevId, nodeId) || null;
      if (takenEdge) takenEdge.closest(".edge").classList.add("is-taken");
    }

    // Error marker on the final step of a crashed program.
    const isErrorStep = trace.error && index === steps.length - 1;
    chart.svg.querySelectorAll(".node.is-error").forEach((n) => n.classList.remove("is-error"));
    if (isErrorStep && node) node.el.classList.add("is-error");

    // Editor line: the step's own line, or the node's line for call/return events.
    const line = step.event === "line" ? step.line : node?.data.line || step.line;
    editor.highlightLine(isErrorStep && trace.error.line ? trace.error.line : line, isErrorStep ? "error" : "active");

    // Text bits.
    ui.slider.value = index;
    ui.label.textContent = `Step ${index + 1} of ${steps.length}`;
    ui.stdout.textContent = trace.stdout.slice(0, step.stdout_len);
    const changed = renderVariables(step, previousIndex >= 0 ? steps[previousIndex] : null);
    updateButtons();

    // Hand over to motion.js (or nothing).
    if (node) effects.nodeEntered(node.el);
    if (takenEdge) effects.travel(chart.dot, takenEdge);
    if (changed.length) effects.variablesChanged(changed);
  }

  /** Fill the variables table. Returns the <tr> rows whose value changed. */
  function renderVariables(step, previous) {
    const sameFrame = previous && previous.func === step.func && previous.depth === step.depth;
    const before = sameFrame ? previous.locals : {};
    ui.scope.textContent = step.func === "<module>" ? "(main program)" : `in ${step.func}()`;
    ui.stack.textContent = step.stack.length > 1
      ? `Call stack: ${step.stack.map((f) => (f === "<module>" ? "main" : `${f}()`)).join(" → ")}`
      : "";

    const rows = [];
    const changedRows = [];
    for (const [name, value] of Object.entries(step.locals)) {
      const tr = document.createElement("tr");
      const nameCell = document.createElement("td");
      const valueCell = document.createElement("td");
      const span = document.createElement("span");
      span.className = "value";
      nameCell.textContent = name;
      span.textContent = value;
      valueCell.appendChild(span);
      tr.append(nameCell, valueCell);
      if (before[name] !== value) {
        tr.classList.add("is-changed");
        changedRows.push(tr);
      }
      rows.push(tr);
    }
    if ("return_value" in step) {
      const tr = document.createElement("tr");
      tr.className = "return-value";
      tr.innerHTML = "<td>returns</td><td><span class='value'></span></td>";
      tr.querySelector(".value").textContent = step.return_value;
      rows.push(tr);
      changedRows.push(tr);
    }
    if (!rows.length) {
      const tr = document.createElement("tr");
      tr.className = "variables__empty";
      tr.innerHTML = "<td colspan='2'>No variables yet</td>";
      rows.push(tr);
    }
    ui.varsBody.replaceChildren(...rows);
    return changedRows;
  }

  function scrollIntoView(el) {
    const box = el.getBoundingClientRect();
    const view = ui.chartBox.getBoundingClientRect();
    if (box.top < view.top || box.bottom > view.bottom || box.left < view.left || box.right > view.right) {
      el.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
    }
  }

  function updateButtons() {
    const atStart = index <= 0;
    const atEnd = index >= steps.length - 1;
    ui.first.disabled = ui.back.disabled = atStart;
    ui.forward.disabled = ui.last.disabled = atEnd;
    ui.play.textContent = timer ? "⏸" : "▶";
    ui.play.setAttribute("aria-label", timer ? "Pause" : "Play");
  }

  // ------------------------------------------------------------------ playing
  function play() {
    if (timer || !steps.length) return;
    if (index >= steps.length - 1) show(0);
    const tick = () => {
      show(index + 1, { travelled: true });
      if (index >= steps.length - 1) return pause(); // reached the end: back to "Play" right away
      timer = setTimeout(tick, effects.stepSeconds(BASE_STEP_SECONDS) * 1000);
    };
    timer = setTimeout(tick, effects.stepSeconds(BASE_STEP_SECONDS) * 1000);
    updateButtons();
  }

  function pause() {
    clearTimeout(timer);
    timer = null;
    updateButtons();
  }

  const controls = {
    play,
    pause,
    toggle: () => (timer ? pause() : play()),
    forward: () => { pause(); show(index + 1, { travelled: true }); },
    back: () => { pause(); show(index - 1); },
    first: () => { pause(); show(0); },
    last: () => { pause(); show(steps.length - 1); },
    goTo: (i) => { pause(); show(i); },
    get index() { return index; },
  };

  // ------------------------------------------------- clicking a node jumps there
  function jumpToNode(nodeId) {
    const hits = nodeIds.map((id, i) => (id === nodeId ? i : -1)).filter((i) => i >= 0);
    if (!hits.length) {
      ui.notify("That part of the flowchart never ran", "None of the steps reached it with this input.");
      return;
    }
    // Next time this node runs after the current step (wrapping around), so
    // clicking a loop node repeatedly walks through its iterations.
    const next = hits.find((i) => i > index) ?? hits[0];
    controls.goTo(next);
  }

  const listeners = [];
  function on(target, type, fn) {
    target.addEventListener(type, fn);
    listeners.push(() => target.removeEventListener(type, fn));
  }
  for (const { el, data } of chart.nodes.values()) {
    on(el, "click", () => jumpToNode(data.id));
    on(el, "keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        jumpToNode(data.id);
      }
    });
  }
  on(ui.play, "click", controls.toggle);
  on(ui.forward, "click", controls.forward);
  on(ui.back, "click", controls.back);
  on(ui.first, "click", controls.first);
  on(ui.last, "click", controls.last);
  on(ui.slider, "input", () => controls.goTo(Number(ui.slider.value)));

  controls.destroy = () => {
    pause();
    effects.stop();
    listeners.forEach((off) => off());
  };

  show(0);
  return controls;
}
