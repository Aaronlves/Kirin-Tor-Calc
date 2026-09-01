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
```

The Vite build uses `/assets/` as its public base and emits JavaScript and CSS
at the root of `dist/`. That layout matches the local Python server's existing
`/assets/<file>` routing and lets the final build replace the legacy assets
without changing the user-facing `kt web` command.
