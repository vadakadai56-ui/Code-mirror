// flowchart.js — draws the graph JSON as an SVG flowchart.
//
// This file only DRAWS. It doesn't animate (that is motion.js) and it doesn't know
// anything about Python (the backend's graph_builder.py already did that work).
//
// Layout idea: the chart has the same shape as the code.
//   * each function gets its own column ("lane"); lane 0 is the main program
//   * `row` from the graph = vertical position, `col` = indentation
//   * edges to the next row go straight down a "spine" near each node's left side
//   * edges that skip rows go around the left side (a "gutter")
//   * edges that go back up (loops) go around the right side
//
// drawFlowchart() returns handles that playback.js and motion.js use:
//   { svg, nodes: Map(id -> {el, data, box}), edges: [{el, data, route}],
//     edgeBetween(fromId, toId) -> SVGPathElement | undefined, dot }

const SVG_NS = "http://www.w3.org/2000/svg";

const NODE_H = 38; // height of every node box
const ROW_H = 64; // vertical distance between rows
const INDENT = 30; // horizontal shift per indentation level
const PAD_X = 14; // text padding inside a box
const MIN_W = 96;
const SPINE = 28; // straight edges leave/enter this far from a node's left edge
const LANE_GAP = 64;
const TOP = 58; // room for lane titles
const SLOT = 12; // distance between parallel gutter lines
const GUTTER_PAD = 18;
const RADIUS = 7; // corner radius for routed edges

// Extra width per shape, for the pointy or barred ends.
const SHAPE_EXTRA = { decision: NODE_H, loop: 22, call: 16, start: 12, end: 12 };
const TYPE_NAMES = {
  start: "start", end: "end", statement: "statement", decision: "decision",
  loop: "loop", call: "function call", return: "return",
};

/** Create an SVG element with attributes. */
function el(tag, attrs = {}, parent) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

// ---------------------------------------------------------------- measuring
let measureCtx;
function textWidth(text) {
  if (!measureCtx) {
    measureCtx = document.createElement("canvas").getContext("2d");
    const mono = getComputedStyle(document.documentElement).getPropertyValue("--mono");
    measureCtx.font = `13px ${mono || "monospace"}`;
  }
  return measureCtx.measureText(text).width;
}

// ------------------------------------------------------------------- layout
/** Work out the size and position of every node, and how every edge is routed. */
export function layoutGraph(graph) {
  const nodes = new Map();
  for (const n of graph.nodes) {
    const w = Math.max(MIN_W, Math.ceil(textWidth(n.label)) + 2 * PAD_X + (SHAPE_EXTRA[n.type] || 0));
    nodes.set(n.id, { data: n, w, h: NODE_H });
  }

  // Decide how each edge travels.
  const edges = graph.edges.map((e) => {
    const a = nodes.get(e.from).data;
    const b = nodes.get(e.to).data;
    let route = "straight";
    if (e.kind === "call") route = a.lane === b.lane ? "right" : "call"; // recursion: up the right side
    else if (e.kind === "back") route = "right";
    else if (b.row > a.row + 1) route = "left";
    const span = route === "right" ? [b.row, a.row] : [a.row, b.row];
    return { data: e, route, lane: a.lane, span, slot: 0 };
  });

  // Give gutter edges a "slot" (distance from the nodes) so lines don't overlap.
  // Short edges get the inner slots, so longer edges wrap around them.
  const slotCount = {};
  for (const side of ["left", "right"]) {
    const byLane = {};
    for (const e of edges.filter((x) => x.route === side)) (byLane[e.lane] ||= []).push(e);
    for (const [lane, list] of Object.entries(byLane)) {
      list.sort((p, q) => p.span[1] - p.span[0] - (q.span[1] - q.span[0]));
      const slots = []; // slots[k] = list of spans already using slot k
      for (const e of list) {
        let k = 0;
        while (slots[k] && slots[k].some((s) => s[0] <= e.span[1] && e.span[0] <= s[1])) k++;
        (slots[k] ||= []).push(e.span);
        e.slot = k;
      }
      slotCount[`${side}${lane}`] = slots.length;
    }
  }

  // Lanes side by side.
  const lanes = graph.lanes.map((lane, index) => {
    const laneNodes = [...nodes.values()].filter((n) => n.data.lane === index);
    const contentW = Math.max(...laneNodes.map((n) => n.data.col * INDENT + n.w));
    const rows = Math.max(...laneNodes.map((n) => n.data.row)) + 1;
    const left = GUTTER_PAD + (slotCount[`left${index}`] || 0) * SLOT;
    const right = GUTTER_PAD + (slotCount[`right${index}`] || 0) * SLOT;
    return { ...lane, index, contentW, rows, left, right, width: left + contentW + right };
  });
  let x = 24;
  for (const lane of lanes) {
    lane.x = x;
    x += lane.width + LANE_GAP;
  }

  for (const n of nodes.values()) {
    const lane = lanes[n.data.lane];
    n.x = lane.x + lane.left + n.data.col * INDENT;
    n.y = TOP + n.data.row * ROW_H;
  }

  const height = TOP + Math.max(...lanes.map((l) => l.rows)) * ROW_H;
  return { nodes, edges, lanes, width: x - LANE_GAP + 24, height };
}

// ------------------------------------------------------------- edge paths
/** A path through the given points with rounded corners. */
function roundedPath(points) {
  let d = `M ${points[0][0]} ${points[0][1]}`;
  for (let i = 1; i < points.length - 1; i++) {
    const [px, py] = points[i - 1];
    const [cx, cy] = points[i];
    const [nx, ny] = points[i + 1];
    const r1 = Math.min(RADIUS, Math.hypot(cx - px, cy - py) / 2);
    const r2 = Math.min(RADIUS, Math.hypot(nx - cx, ny - cy) / 2);
    const inX = cx - Math.sign(cx - px) * r1;
    const inY = cy - Math.sign(cy - py) * r1;
    const outX = cx + Math.sign(nx - cx) * r2;
    const outY = cy + Math.sign(ny - cy) * r2;
    d += ` L ${inX} ${inY} Q ${cx} ${cy} ${outX} ${outY}`;
  }
  const last = points[points.length - 1];
  return d + ` L ${last[0]} ${last[1]}`;
}

function edgeGeometry(edge, layout) {
  const a = layout.nodes.get(edge.data.from);
  const b = layout.nodes.get(edge.data.to);
  const midA = a.y + a.h / 2;
  const midB = b.y + b.h / 2;

  if (edge.route === "straight") {
    const sx = a.x + SPINE, sy = a.y + a.h;
    const tx = b.x + SPINE, ty = b.y;
    const bend = (ty - sy) / 2;
    return {
      d: `M ${sx} ${sy} C ${sx} ${sy + bend} ${tx} ${ty - bend} ${tx} ${ty}`,
      labelAt: [sx + 6, sy + 13, "start"],
    };
  }
  if (edge.route === "left") {
    const lane = layout.lanes[a.data.lane];
    const gx = lane.x + lane.left - 10 - edge.slot * SLOT;
    return {
      d: roundedPath([[a.x, midA], [gx, midA], [gx, midB], [b.x, midB]]),
      labelAt: [a.x - 6, midA - 6, "end"],
    };
  }
  if (edge.route === "right") {
    const lane = layout.lanes[a.data.lane];
    const gx = lane.x + lane.left + lane.contentW + 10 + edge.slot * SLOT;
    return {
      d: roundedPath([[a.x + a.w, midA], [gx, midA], [gx, midB], [b.x + b.w, midB]]),
      labelAt: [a.x + a.w + 6, midA - 6, "start"],
    };
  }
  // call: a soft curve from the calling line across to the function's start
  const sx = a.x + a.w, tx = b.x;
  const pull = Math.max(60, (tx - sx) / 2);
  return { d: `M ${sx} ${midA} C ${sx + pull} ${midA} ${tx - pull} ${midB} ${tx} ${midB}`, labelAt: null };
}

// ------------------------------------------------------------- node shapes
function shapeFor(type, w, h) {
  const m = h / 2;
  switch (type) {
    case "decision": // pointy ends: a stretched diamond
      return ["polygon", { points: `0,${m} ${m},0 ${w - m},0 ${w},${m} ${w - m},${h} ${m},${h}` }];
    case "loop": // hexagon, the classic "preparation" symbol for loops
      return ["polygon", { points: `0,${m} 11,0 ${w - 11},0 ${w},${m} ${w - 11},${h} 11,${h}` }];
    case "start":
    case "end":
      return ["rect", { width: w, height: h, rx: m }];
    default:
      return ["rect", { width: w, height: h, rx: 6 }];
  }
}

// ------------------------------------------------------------------ drawing
/** Replace the contents of `container` with a new flowchart for `graph`. */
export function drawFlowchart(container, graph) {
  const layout = layoutGraph(graph);
  const svg = el("svg", {
    class: "flowchart",
    width: layout.width,
    height: layout.height,
    viewBox: `0 0 ${layout.width} ${layout.height}`,
    role: "group",
    "aria-label": "Flowchart of your program",
  });

  const defs = el("defs", {}, svg);
  for (const [id, cls] of [["arrow", "arrowhead"], ["arrow-call", "arrowhead arrowhead--call"]]) {
    const marker = el("marker", {
      id, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse",
    }, defs);
    el("path", { d: "M 0 0 L 10 5 L 0 10 z", class: cls }, marker);
  }

  // Lane backgrounds and titles.
  const laneLayer = el("g", { class: "lanes" }, svg);
  for (const lane of layout.lanes) {
    el("rect", { class: "lane", x: lane.x - 8, y: 8, width: lane.width + 16, height: layout.height - 16, rx: 12 }, laneLayer);
    const title = el("text", { class: "lane__title", x: lane.x + lane.left, y: 36 }, laneLayer);
    title.textContent = lane.title;
  }

  // Edges first, so nodes are drawn on top of them.
  const edgeLayer = el("g", { class: "edges" }, svg);
  const edges = layout.edges.map((edge) => {
    const geo = edgeGeometry(edge, layout);
    const group = el("g", { class: `edge edge--${edge.data.kind} edge--${edge.route}` }, edgeLayer);
    const path = el("path", {
      d: geo.d,
      class: "edge__line",
      "marker-end": edge.data.kind === "call" ? "url(#arrow-call)" : "url(#arrow)",
    }, group);
    path.dataset.from = edge.data.from;
    path.dataset.to = edge.data.to;
    if (edge.data.label && geo.labelAt) {
      const [lx, ly, anchor] = geo.labelAt;
      const text = el("text", { class: "edge__label", x: lx, y: ly, "text-anchor": anchor }, group);
      text.textContent = edge.data.label;
    }
    return { el: path, group, data: edge.data, route: edge.route };
  });

  // Nodes.
  const nodeLayer = el("g", { class: "nodes" }, svg);
  const nodes = new Map();
  for (const n of layout.nodes.values()) {
    const d = n.data;
    const g = el("g", {
      class: `node node--${d.type}`,
      transform: `translate(${n.x} ${n.y})`,
      tabindex: d.line ? 0 : -1,
      role: d.line ? "button" : "img",
      "aria-label": `${TYPE_NAMES[d.type]}${d.line ? `, line ${d.line}` : ""}: ${d.label}`,
    }, nodeLayer);
    g.dataset.id = d.id;
    // Inner group: motion.js scales this one, so the outer translate stays untouched.
    const body = el("g", { class: "node__body" }, g);
    const [tag, attrs] = shapeFor(d.type, n.w, n.h);
    el(tag, { ...attrs, class: "node__shape" }, body);
    if (d.type === "call") {
      // "predefined process" symbol: two inner vertical bars
      el("line", { x1: 8, y1: 0, x2: 8, y2: n.h, class: "node__bar" }, body);
      el("line", { x1: n.w - 8, y1: 0, x2: n.w - 8, y2: n.h, class: "node__bar" }, body);
    }
    const label = el("text", { class: "node__label", x: n.w / 2, y: n.h / 2 + 4.5, "text-anchor": "middle" }, body);
    label.textContent = d.label;
    if (d.line) {
      // Line number as a small tag just outside the top-left corner.
      const num = el("text", { class: "node__line", x: -4, y: -3, "text-anchor": "end" }, g);
      num.textContent = d.line;
    }
    nodes.set(d.id, { el: g, data: d, box: { x: n.x, y: n.y, w: n.w, h: n.h } });
  }

  // The playback dot (motion.js moves it along edges). Hidden until used.
  const dot = el("circle", { class: "dot", r: 5, cx: -20, cy: -20, opacity: 0 }, svg);

  container.replaceChildren(svg);

  const edgeIndex = new Map(edges.filter((e) => e.data.kind !== "call").map((e) => [`${e.data.from}>${e.data.to}`, e.el]));
  return {
    svg,
    nodes,
    edges,
    dot,
    edgeBetween: (fromId, toId) => edgeIndex.get(`${fromId}>${toId}`),
  };
}
