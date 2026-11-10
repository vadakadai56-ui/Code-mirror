// motion.js — ALL animation in Code Mirror lives here (see the code-mirror-motion skill).
//
// Other files never animate. They call these functions:
//   animateEntrance(chart)       nodes fade/scale in with a stagger, edges draw themselves
//   crossFade(oldSvg, container) the previous chart fades out under the new one
//   effects.nodeEntered(el)      the active node pops and springs back
//   effects.travel(dot, path)    a dot runs along the edge that was just taken
//   effects.variablesChanged(rows)  changed values slide in and their row flashes
//   setSpeed(x)                  the speed slider: scales EVERY duration and the step clock
//
// Rules: every duration/delay goes through dur(); prefers-reduced-motion turns
// durations to 0 and skips purely decorative motion (pulse, dot, slide).

import { animate, stagger, spring } from "https://cdn.jsdelivr.net/npm/motion@14.6.0/+esm";

// ---------------------------------------------------------------- settings
let speed = 1;
const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
let reducedMotion = reduceQuery.matches;
reduceQuery.addEventListener("change", (e) => { reducedMotion = e.matches; });

/** Duration or delay in seconds, scaled by the speed slider (0 with reduced motion). */
const dur = (seconds) => (reducedMotion ? 0 : seconds / speed);

/** Spring options whose length also follows the speed slider. */
const springAt = ({ visualDuration = 0.4, bounce = 0.3 } = {}) => ({
  type: spring,
  visualDuration: dur(visualDuration),
  bounce,
});

export function setSpeed(value) { speed = value; }
export function isReducedMotion() { return reducedMotion; }

// Keep the controls of running animations so we can stop them (e.g. on a new chart).
const running = new Set();
function track(controls) {
  running.add(controls);
  controls.finished.then(() => running.delete(controls), () => running.delete(controls));
  return controls;
}
export function stopAll() {
  for (const c of running) c.stop();
  running.clear();
}

// ----------------------------------------------------------------- entrance
/** Nodes fade and scale in, top to bottom; each edge draws itself after its source node. */
export function animateEntrance(chart) {
  if (reducedMotion) return; // the static chart is already in its final state
  const nodes = [...chart.nodes.values()].sort((a, b) => a.data.lane - b.data.lane || a.data.row - b.data.row);
  // Big charts get a shorter stagger so the whole entrance stays under about a second.
  const gap = Math.min(0.035, 0.9 / Math.max(1, nodes.length));
  const order = new Map(nodes.map((n, i) => [n.data.id, i]));

  track(animate(nodes.map((n) => n.el), { opacity: [0, 1] }, { duration: dur(0.3), delay: stagger(dur(gap)) }));
  track(animate(
    nodes.map((n) => n.el.querySelector(".node__body")),
    { scale: [0.85, 1] },
    { ...springAt({ visualDuration: 0.35, bounce: 0.25 }), delay: stagger(dur(gap)) },
  ));

  for (const edge of chart.edges) {
    const path = edge.el;
    const length = path.getTotalLength();
    const delay = dur(gap * order.get(edge.data.from) + 0.12);
    // Draw the line by sliding a dash the length of the whole path into view.
    path.style.strokeDasharray = `${length}`;
    const draw = track(animate(path, { strokeDashoffset: [length, 0], opacity: [0, 1] }, {
      duration: dur(0.45), delay, ease: "easeOut",
    }));
    // Afterwards, hand the dash pattern back to CSS (call edges are dashed).
    draw.finished.then(() => { path.style.strokeDasharray = ""; path.style.strokeDashoffset = ""; });
    const label = edge.group.querySelector(".edge__label");
    if (label) track(animate(label, { opacity: [0, 1] }, { duration: dur(0.3), delay: delay + dur(0.2) }));
  }
}

// --------------------------------------------------------------- cross-fade
/** Fade out the previous chart on top of the new one, then remove it. */
export function crossFade(oldSvg, container) {
  if (!oldSvg) return;
  if (reducedMotion) return oldSvg.remove();
  oldSvg.classList.add("flowchart--leaving");
  container.prepend(oldSvg); // same grid cell as the new chart (see .chart in style.css)
  track(animate(oldSvg, { opacity: [1, 0] }, { duration: dur(0.35), ease: "easeOut" }))
    .finished.then(() => oldSvg.remove(), () => oldSvg.remove());
}

// ------------------------------------------------------------------ playback
let pulse = null; // {controls, body} of the node that is pulsing now
let dotRun = null;

export const effects = {
  /** The active node pops slightly larger and springs back. */
  nodeEntered(nodeEl) {
    if (reducedMotion) return; // the static highlight (colour + outline) is enough
    if (pulse) {
      // Stopping a spring freezes it mid-way, so ease the previous node back to its normal size.
      pulse.controls.stop();
      if (pulse.body !== nodeEl.querySelector(".node__body")) {
        track(animate(pulse.body, { scale: 1 }, { duration: dur(0.12) }));
      }
    }
    const body = nodeEl.querySelector(".node__body");
    pulse = { body, controls: track(animate(body, { scale: [1.1, 1] }, springAt({ visualDuration: 0.45, bounce: 0.5 }))) };
  },

  /** A dot travels along the edge from the previous node to the new one. */
  travel(dot, path) {
    if (reducedMotion) return;
    dotRun?.stop();
    const length = path.getTotalLength();
    const place = (p) => {
      const point = path.getPointAtLength(p * length);
      dot.setAttribute("cx", point.x);
      dot.setAttribute("cy", point.y);
    };
    place(0);
    dot.style.opacity = 1; // Motion animates opacity as a style, so use the style here too
    dotRun = track(animate(0, 1, { duration: dur(0.32), ease: "easeInOut", onUpdate: place }));
    dotRun.finished.then(() => track(animate(dot, { opacity: 0 }, { duration: dur(0.2) })), () => {});
  },

  /** Changed variables: the value slides in and the row flashes. */
  variablesChanged(rows) {
    if (reducedMotion) return; // .is-changed already colours them
    for (const row of rows) {
      const value = row.querySelector(".value");
      track(animate(value, { x: [-10, 0], opacity: [0, 1] }, { duration: dur(0.28), ease: "easeOut" }));
      track(animate(row, { backgroundColor: ["rgba(255, 207, 92, 0.32)", "rgba(255, 207, 92, 0)"] },
        { duration: dur(0.7), ease: "easeOut" }));
    }
  },

  /** How long a step stays on screen while playing (scaled by speed, never 0). */
  stepSeconds: (seconds) => seconds / speed,

  stop: stopAll,
};
