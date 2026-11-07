---
name: code-mirror-motion
description: Animation conventions for the Code Mirror frontend. Use this skill whenever you add, change, tune or debug any movement in Code Mirror - node or edge entrance, the active-node pulse, the dot travelling along an edge, the variables panel flashing, cross-fading between examples, the playback speed slider, or prefers-reduced-motion behaviour. Also use it when any static/*.js file is about to animate something, so that the code goes through motion.js and not CSS transitions or setTimeout tricks.
---

# Code Mirror motion conventions

Code Mirror uses the **Motion** library (motion.dev) in vanilla JS, loaded as an ES
module from a CDN with no build step.

## Rule 1: all animation code lives in `static/motion.js`

- `motion.js` is the **only** file that imports Motion and the only file that animates.
- Other modules call its exported functions, for example `animateEntrance(svg)`,
  `pulseNode(el)`, `moveDot(pathEl)`, `flashVariable(row)`, `crossFade(oldSvg, newSvg)`.
  They never call `animate()` directly and never add CSS transitions for movement.
- Why: the speed slider and reduced motion have to apply to *every* animation. That
  only works reliably when everything goes through one place.
- Drawing code (`flowchart.js`) builds the final, static SVG. Motion only animates
  *from* a start state *to* that final state, so the chart is correct even if
  animation fails or is skipped.

## Rule 2: one pinned import

```js
import { animate, stagger, spring } from "https://cdn.jsdelivr.net/npm/motion@14.6.0/+esm";
```

The version is pinned on purpose: `@latest` moves every few days and Motion 14 is a new
major. Bump it only deliberately, re-run the browser tests, and update this line here.

## Rule 3: the speed slider scales every duration

`motion.js` keeps one `speed` value (1 = normal; the slider goes from 0.25× to 4×) and
every timing goes through two helpers:

```js
export function setSpeed(value) { speed = value; }
const dur = (seconds) => (reducedMotion ? 0 : seconds / speed);  // durations and delays
const springAt = (opts) => ({ type: spring, ...opts, visualDuration: dur(opts.visualDuration ?? 0.4) });
```

- Never pass a literal `duration:` or `delay:` to `animate()`. Always use `dur(...)`,
  including the `stagger(dur(0.04))` interval.
- Playback timing (how long each step stays on screen) also uses the same `speed`, so
  the dot and the step clock stay in sync.

## Rule 4: respect prefers-reduced-motion

```js
const query = window.matchMedia("(prefers-reduced-motion: reduce)");
let reducedMotion = query.matches;
query.addEventListener("change", (e) => { reducedMotion = e.matches; });
```

When `reducedMotion` is true:
- Durations become 0 (via `dur`), so elements jump straight to their final state.
- Decorative motion is skipped completely: no pulse scale and no travelling dot. The
  active node is still shown with a static highlight (colour and outline), so no
  information is lost.
- A changed variable is still marked with a colour change instead of a slide.

## The animations and the Motion API used

Timings below are at speed 1×.

| Effect | How | Motion API |
|---|---|---|
| Node entrance | opacity 0→1, scale 0.85→1, staggered by row | `animate(nodes, {opacity:[0,1], scale:[0.85,1]}, {duration: dur(0.35), delay: stagger(dur(0.04))})` |
| Edge draws itself | `stroke-dasharray = length`, animate `strokeDashoffset` length→0 (use `path.getTotalLength()`) | `animate(path, {strokeDashoffset: [len, 0]}, {duration: dur(0.5), delay: ...})` |
| Active node pulse | quick scale up and settle back with a spring | `animate(el, {scale: [1, 1.08, 1]}, springAt({bounce: 0.4}))` |
| Dot follows edge | animate a progress value 0→1 and place the dot with `path.getPointAtLength(p * len)` | `animate(0, 1, {duration: dur(0.3), onUpdate: p => ...})` |
| Variable changed | value slides in from the left and the row background flashes | `animate(cell, {x: [-8, 0], opacity: [0, 1]}, ...)` and `animate(row, {backgroundColor: [flash, "transparent"]}, ...)` |
| Example switch | old SVG fades out while the new one fades in (both in the same grid cell) | two `animate()` calls, then remove the old SVG on finish |

Notes:
- Durations are in **seconds** (not ms).
- SVG transforms: set `transform-box: fill-box; transform-origin: center` in CSS on
  node groups, so `scale` grows from the node's centre.
- Cancel animations that are still running before starting new ones on the same element
  (keep the control object `animate()` returns and call `.stop()`), so fast stepping
  doesn't stack pulses.
- If an API detail is unclear, check motion.dev docs. If they can't be reached (as in
  the cloud dev container), read the type definitions in the npm package:
  `npm pack motion@14.6.0`, and look at `motion-dom/dist/index.d.ts` after installing.

## Testing animations

- The cloud dev container blocks `cdn.jsdelivr.net`. The browser tests serve a locally
  bundled copy of the same version through Playwright's `page.route`. See the
  code-mirror-testing skill. Never change the app's import URL to make tests pass.
- Test with `reduced_motion="reduce"` too: the final state must be identical and no
  animation should be left running.
