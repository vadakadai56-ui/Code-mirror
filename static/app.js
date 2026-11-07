// app.js — wires the page together: editor, examples menu, Visualize button,
// the flowchart and the error/output panels.
//
// Data flow:  editor text --POST /api/visualize--> {graph, trace}
//             graph --> flowchart.js (draw)      trace --> output panel (+ playback in stage 4)

import { createEditor } from "./editor.js";
import { drawFlowchart } from "./flowchart.js";

const $ = (id) => document.getElementById(id);

const editor = createEditor({ textarea: $("code"), gutter: $("gutter"), highlight: $("line-highlight") });
const chartBox = $("chart");
const messageBox = $("message");
const stdoutBox = $("stdout");
const visualizeBtn = $("visualize-btn");
const exampleSelect = $("example-select");

let examples = [];

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
  stdoutBox.textContent = trace.stdout;
  showTraceProblems(trace);
  if (!graph) {
    // Syntax error: there's nothing to draw.
    const p = document.createElement("p");
    p.className = "chart__empty";
    p.textContent = "Fix the syntax error, then press Visualize again.";
    chartBox.replaceChildren(p);
    return null;
  }
  return drawFlowchart(chartBox, graph);
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
  for (const ex of examples) {
    const option = document.createElement("option");
    option.value = ex.id;
    option.textContent = ex.title;
    exampleSelect.appendChild(option);
  }
  exampleSelect.addEventListener("change", () => loadExample(exampleSelect.value));
  visualizeBtn.addEventListener("click", visualize);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      visualize();
    }
  });
  loadExample(examples[0].id);
}

init();
