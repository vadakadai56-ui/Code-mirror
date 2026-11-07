---
name: code-mirror-motion
description: Animation conventions for the Code Mirror frontend. Use this skill whenever you add, change, tune or debug any movement in Code Mirror - node or edge entrance, the active-node pulse, the dot travelling along an edge, the variables panel flashing, cross-fading between examples, the playback speed slider, or prefers-reduced-motion behaviour. Also use it when any static/*.js file is about to animate something, so that the code goes through motion.js and not CSS transitions or setTimeout tricks.
---

# Code Mirror motion conventions

Code Mirror uses the **Motion** library (motion.dev) in vanilla JS, loaded as an ES
module from a CDN with no build step.

## Rule 1: all animation code lives in `static/motion.js`

- `motion.js` is the **only** file that imports Motion and the only file that animates.
- Its public API (keep this list in sync with the file):
  - `animateEntrance(chart)`: called by app.js after `drawFlowchart`.
  - `crossFade(oldSvg, container)`: called by app.js with the previous chart's `<svg>`.
  - `effects`: the object playback.js calls on every step. It contains
    `nodeEntered(nodeEl)` (pulse), `travel(dot, path)` (dot along the taken edge),
    `variablesChanged(rows)` (slide and flash), `stepSeconds(s)` (play clock) and `stop()`.
  - `setSpeed(x)`, `isReducedMotion()`, `stopAll()`.
- Other modules never call `animate()` directly and never add CSS transitions for movement.
- app.js loads motion.js with a **dynamic `import()`** and keeps a no-op fallback with
  the same shape. If the CDN is down, the app still works without animation. If you
  add a function to motion.js, add a no-op version to that fallback in app.js too.
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
- Before starting a new animation on the same element, stop the one that is still
  running (keep the control object `animate()` returns and call `.stop()`), so fast
  stepping doesn't stack pulses. Then reset the element (see Gotchas).
- If an API detail is unclear, check motion.dev docs. If they can't be reached (as in
  the cloud dev container), read the type definitions in the npm package:
  `npm pack motion@14.6.0`, and look at `motion-dom/dist/index.d.ts` after installing.

## Gotchas learned while building it

- **Motion applies values on its next animation frame.** Reading `style.transform`
  right after a click shows the *old* value. In tests, read after two
  `requestAnimationFrame`s (`after_frames()` in `tests/e2e/test_motion.py`).
- Spring and number animations (the pulse, and `animate(0, 1, {onUpdate})` for the dot)
  run in JS, so `document.getAnimations()` doesn't list them. Check the element's
  style instead.
- `controls.stop()` **freezes** an animation where it is. When you interrupt a pulse
  (fast stepping), also animate the old element back to its resting value, as
  `effects.nodeEntered` does. Otherwise nodes stay slightly enlarged
  (regression test: `test_fast_stepping_leaves_no_node_stuck_enlarged`).
- Springs take exactly **two** keyframes. A "pop" is done as `scale: [1.1, 1]`
  (jump up, spring back), not `[1, 1.1, 1]`.
- `opacity` on SVG elements is set as a *style*, and the style overrides the `opacity`
  attribute. Use `el.style.opacity` for anything Motion also animates.
- Scaling an SVG `<g>` needs `transform-box: fill-box; transform-origin: center`, and we
  scale the inner `.node__body` so the outer group's `translate(...)` stays intact.
- The edge "draw" sets an inline `stroke-dasharray`. Clear it when the draw finishes,
  so dashed call edges get their CSS dash pattern back.
- At 0.25× the bubble-sort entrance takes about 4.5 s, because stagger, delays and
  durations all scale. Tests that wait for "settled" must allow for that.
- While charts cross-fade, there are briefly **two** `.flowchart` SVGs in the page.
  Selectors in code and tests should skip `.flowchart--leaving` (the e2e helpers
  `load_example()` and `visualize()` wait for it to be removed).

## Testing animations

- The cloud dev container blocks `cdn.jsdelivr.net`. The browser tests serve a locally
  bundled copy of the same version through Playwright's `page.route`. See the
  code-mirror-testing skill. Never change the app's import URL to make tests pass.
- Test with `reduced_motion="reduce"` too (the `reduced_page` fixture): the final state
  must be identical, `document.getAnimations()` must be empty, and the dot must stay hidden.
- `tests/e2e/test_motion.py` covers the entrance, cross-fade, speed scaling (dot timing at
  0.25× vs 4×), pulse, variable flash, reduced motion, and running without the CDN.
- `tests/e2e/vendor/motion-<version>.esm.js` must match the pinned version.
  `test_vendored_motion_matches_pinned_version` checks this, and also that only
  motion.js imports Motion. When bumping the version, rebuild the bundle as described in
  `tests/e2e/vendor/README.md`.
