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
npx playwright install chromium
npm run test:e2e
```

The Vite build uses `/assets/` as its public base and emits JavaScript and CSS
at the root of `dist/`. That layout matches the local Python server's existing
`/assets/<file>` routing and lets the final build replace the legacy assets
without changing the user-facing `kt web` command.

The Playwright suite builds the current frontend, serves it against a disposable copy of the
fictional example workspace, and covers document switching, completion insertion, preview inputs
and results, chart expansion, diagnostic navigation, responsive panel state, keyboard graph
navigation, creation validation, and external-change recovery. It never writes to the example
workspace itself.
