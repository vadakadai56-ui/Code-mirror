# Test-only copy of Motion

`motion-14.6.0.esm.js` is the Motion library (motion.dev, MIT licence, see
`MOTION-LICENSE.md`), version 14.6.0, bundled into one ES module with esbuild:

    npm install motion@14.6.0 esbuild
    echo 'export * from "motion";' > entry.mjs
    npx esbuild entry.mjs --bundle --format=esm --minify --outfile=motion-14.6.0.esm.js

The app itself always loads Motion from the CDN (`static/motion.js`). The browser
tests swap in this file with Playwright's `page.route` so they also work where the
CDN is blocked. Keep its version equal to the one pinned in `static/motion.js`.
