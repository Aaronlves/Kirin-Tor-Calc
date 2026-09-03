# Kirin Tor Web Workbench frontend

This directory contains the current React/TypeScript source for the browser
workbench. Vite writes a production build to `frontend/dist/`; the checked-in
copy under `src/kirin_tor/web_assets/` is the packaged runtime served by
`kt web`. The two directories must remain byte-for-byte identical after a
frontend change.

```bash
cd frontend
npm install
npm run tokens:check
npm run design:check
npm run typecheck
npm run build
npx playwright install chromium firefox webkit
npm run test:e2e
npm run test:bundle
```

Visual decisions are owned by the eight-family token source in
`src/design/tokens.json`; see [the design-system contract](../docs/design-system.md).
Edit that source, run `npm run tokens:generate`, and commit the generated
`src/design/tokens.css` with the change. The build rejects stale generated CSS,
unknown token references, and unmanaged visual literals.

The Vite build uses `/assets/` as its public base and emits JavaScript and CSS
at the root of `dist/`. That layout matches the local Python server's
`/assets/<file>` routing. After a production build, synchronize the complete
contents of `frontend/dist/` into `src/kirin_tor/web_assets/`; do not edit the
generated runtime assets by hand. Verify synchronization with:

```bash
cd ..
diff -qr frontend/dist src/kirin_tor/web_assets
```

The Playwright suite builds the frontend and serves it against disposable
workspaces. It covers the main authoring, projection, navigation, recovery,
workspace-search, document-lifecycle, syntax-reference, tutorial, graph, and
conflict flows. Chromium, Firefox, and WebKit run the functional suite;
axe-core checks key surfaces and Chromium/WebKit retain layout screenshots.
Tests never write to the checked-in repository example.

`npm run test:bundle` enforces explicit entry, largest-chunk, total-JavaScript, and total-CSS byte budgets.
CI also compares `frontend/dist/` byte-for-byte with `src/kirin_tor/web_assets/` and runs the synthetic
100-document validation benchmark in `scripts/benchmark_workbench.py`.
