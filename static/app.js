// app.js — wires the page together: editor, examples menu, Visualize button,
// the flowchart and the error/output panels.
//
// Data flow:  editor text --POST /api/visualize--> {graph, trace}
//             graph --> flowchart.js (draw)      graph + trace --> playback.js (step through)

import { createEditor } from "./editor.js";
import { drawFlowchart } from "./flowchart.js";
import { createPlayback } from "./playback.js";

const $ = (id) => document.getElementById(id);

const editor = createEditor({ textarea: $("code"), gutter: $("gutter"), highlight: $("line-highlight") });
const chartBox = $("chart");
const messageBox = $("message");
const stdoutBox = $("stdout");
const visualizeBtn = $("visualize-btn");
const exampleSelect = $("example-select");

let examples = [];
let playback = null; // the current playback controls (replaced on every Visualize)

// Animations come from motion.js, which loads the Motion library from a CDN.
// It is imported dynamically so that, if the CDN can't be reached, the app still
// works: `motion` stays a fallback with instant (non-animated) changes.
let speed = 1;
let motion = {
  setSpeed: (value) => { speed = value; },
  animateEntrance() {},
  crossFade: (oldSvg) => oldSvg?.remove(),
  effects: {
    nodeEntered() {},
    travel() {},
    variablesChanged() {},
    stepSeconds: (seconds) => seconds / speed,
    stop() {},
  },
};
const motionReady = import("./motion.js")
  .then((module) => { motion = module; motion.setSpeed(speed); })
  .catch((err) => console.warn("Animations are off: the Motion library could not be loaded.", err));

const playbackUi = {
  root: $("playback"),
  play: $("btn-play"),
  forward: $("btn-forward"),
  back: $("btn-back"),
  first: $("btn-first"),
  last: $("btn-last"),
  slider: $("step-slider"),
  label: $("step-label"),
  stdout: stdoutBox,
  variables: $("variables"),
  varsBody: $("vars-body"),
  scope: $("vars-scope"),
  stack: $("call-stack"),
  chartBox,
  notify: (title, detail) => showMessage(title, ` ${detail}`, "info"),
};

// ------------------------------------------------------------------ messages
const ERROR_TITLES = {
  syntax: "Syntax error",
  blocked: "Not allowed in Code Mirror",
  runtime: "Your program stopped with an error",
  timeout: "Time limit reached",
  crash: "The program crashed",
};

function showMessage(title, detail, kind = "error") {
  messageBox.className = `message${kind === "info" ? " message--info" : ""}`;
  messageBox.replaceChildren();
  const strong = document.createElement("strong");
  strong.textContent = title;
  messageBox.append(strong, document.createTextNode(detail));
  messageBox.hidden = false;
}

function hideMessage() {
  messageBox.hidden = true;
}

function showTraceProblems(trace) {
  if (trace.error) {
    const where = trace.error.line ? ` (line ${trace.error.line})` : "";
    showMessage(ERROR_TITLES[trace.error.kind] || "Error", `${trace.error.message}${where}`);
    if (trace.error.line) editor.highlightLine(trace.error.line, "error");
  } else if (trace.truncated) {
    showMessage(
      "Stopped after 500 steps",
      "Code Mirror shows at most 500 steps. If you didn't expect that many, look for a loop that never ends.",
      "info",
    );
  } else {
    hideMessage();
  }
}

// ----------------------------------------------------------------- visualize
async function visualize() {
  const code = editor.getValue();
  visualizeBtn.disabled = true;
  visualizeBtn.textContent = "Running…";
  editor.clearHighlight();
  try {
    const response = await fetch("/api/visualize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    const data = await response.json();
    if (!response.ok) {
      showMessage("Can't visualize yet", data.error || "The server said no.");
      return;
    }
    render(data);
  } catch (err) {
    showMessage("Can't reach the Code Mirror server", " Is `python app.py` still running?");
  } finally {
    visualizeBtn.disabled = false;
    visualizeBtn.textContent = "Visualize";
  }
}

/** Draw the graph and show output. Returns the chart handles (used by playback). */
function render({ graph, trace }) {
  playback?.destroy();
  playback = null;
  stdoutBox.textContent = trace.stdout;
  showTraceProblems(trace);
  if (!graph) {
    playbackUi.root.hidden = playbackUi.variables.hidden = true;
    // Syntax error: there's nothing to draw.
    const p = document.createElement("p");
    p.className = "chart__empty";
    p.textContent = "Fix the syntax error, then press Visualize again.";
    chartBox.replaceChildren(p);
    return null;
  }
  const oldSvg = chartBox.querySelector(".flowchart:not(.flowchart--leaving)");
  const chart = drawFlowchart(chartBox, graph);
  motion.crossFade(oldSvg, chartBox); // previous chart fades out underneath
  motion.animateEntrance(chart);
  playback = createPlayback({ chart, graph, trace, editor, ui: playbackUi, effects: motion.effects });
  return chart;
}

// ------------------------------------------------------------------ examples
function loadExample(id) {
  const example = examples.find((e) => e.id === id);
  if (!example) return;
  editor.setValue(example.code);
  visualize();
}

async function init() {
  examples = await (await fetch("/api/examples")).json();
  await motionReady; // so the very first chart already animates in
  for (const ex of examples) {
    const option = document.createElement("option");
    option.value = ex.id;
    option.textContent = ex.title;
    exampleSelect.appendChild(option);
  }
  exampleSelect.addEventListener("change", () => loadExample(exampleSelect.value));
  visualizeBtn.addEventListener("click", visualize);
  document.addEventListener("keydown", onKey);
  $("code").addEventListener("input", () => editor.clearHighlight()); // the old trace no longer matches

  const speedSlider = $("speed-slider");
  speedSlider.addEventListener("input", () => {
    speed = Number(speedSlider.value);
    motion.setSpeed(speed);
    $("speed-label").textContent = `${speed}×`;
  });
  loadExample(examples[0].id);
}

/** Keyboard shortcuts. Arrow keys etc. only when you're not typing in the editor. */
function onKey(e) {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    visualize();
    return;
  }
  const typing = ["TEXTAREA", "INPUT", "SELECT"].includes(e.target.tagName);
  const onNode = e.target.closest?.(".node");
  if (!playback || typing || e.altKey || e.ctrlKey || e.metaKey) return;
  const actions = {
    ArrowRight: playback.forward,
    ArrowLeft: playback.back,
    Home: playback.first,
    End: playback.last,
    " ": onNode ? null : playback.toggle, // Space on a node means "jump here"
  };
  const action = actions[e.key];
  if (action && !(e.target.tagName === "BUTTON" && e.key === " ")) {
    e.preventDefault();
    action();
  }
}

init();
