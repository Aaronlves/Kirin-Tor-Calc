# Kirin Tor Web Workbench frontend

This directory contains the next React/TypeScript frontend. During the staged
migration, `src/kirin_tor/web_assets/` remains the runtime frontend served by
`kt web`; a frontend build is isolated in `frontend/dist/` until all views are
ported and the server asset switch is verified.

```bash
cd frontend
npm install
npm run typecheck
npm run build
npx playwright install chromium firefox webkit
npm run test:e2e
npm run test:bundle
```

The Vite build uses `/assets/` as its public base and emits JavaScript and CSS
at the root of `dist/`. That layout matches the local Python server's existing
`/assets/<file>` routing and lets the final build replace the legacy assets
without changing the user-facing `kt web` command.

The Playwright suite builds the current frontend, serves it against a disposable copy of the
fictional example workspace, and covers document switching, completion insertion, read-only
automatic result, chart, and formula projections, chart expansion, diagnostic navigation,
source traceability, persisted document focus modes, find/replace, symbol outlines, cross-document
definition and reference navigation, validated rename, parameter hints, safe formatting, directional
local-graph exploration, keyboard graph navigation, searchable and contextual syntax-reference examples,
workspace search/replace, change review, document duplication, creation validation, draft-session recovery,
empty-workspace tutorial viewing and draft copying, and external-change recovery. Chromium, Firefox, and WebKit run the functional suite; axe-core checks key
surfaces and Chromium/WebKit keep layout screenshots. The server uses a disposable copy of the example
workspace, so tests never write to the checked-in example itself.

`npm run test:bundle` enforces explicit entry, largest-chunk, total-JavaScript, and total-CSS byte budgets.
CI also compares `frontend/dist/` byte-for-byte with `src/kirin_tor/web_assets/` and runs the synthetic
100-document validation benchmark in `scripts/benchmark_workbench.py`.
