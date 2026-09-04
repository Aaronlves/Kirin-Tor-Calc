# Kirin Tor Plugin SDK v2

`kirin-plugin-sdk.mjs` is the generated, dependency-free browser SDK for sandboxed Workbench
Plugins. Vendor the file into the Plugin's own `web/` directory; Plugin frames cannot load a remote
package or use the Workbench session token. TypeScript resolves the adjacent
`kirin-plugin-sdk.d.mts`, whose action payloads are generated from the same request schemas.

```js
import { createKirinPlugin } from "./kirin-plugin-sdk.mjs";

const kirin = createKirinPlugin({ api: 2 });
await kirin.ready();

const outputs = await kirin.model.all({ kind: ["output"], limit: 100 });
const values = await kirin.operations.evaluateMany({
  targets: outputs.slice(0, 2).map((item) => item.id),
});
await kirin.results.present(values.operation_id, { title: "Current Build" });

const compact = await kirin.storage.get("ui.compact");
if (!compact.found) await kirin.storage.set("ui.compact", false);

const buildTemplate = kirin.context.templates.find(
  (item) => item.bindings.includes("coefficient"),
);
if (!buildTemplate) throw new Error("Required Build template is unavailable");
await kirin.proposals.submit({
  title: "Create a reviewed Build draft",
  changes: [{
    kind: "create-from-template",
    template: buildTemplate.value,
    document_id: "reviewed_build",
    bindings: { coefficient: "0.5" },
  }],
});
```

`analyze` returns a job handle. Use `kirin.jobs.wait(handle)`, `status(jobId)`, `cancel(jobId)`, or
`onUpdate(listener)`. The SDK supplies the current workspace revision, validates request shapes and
limits, correlates replies, and normalizes stable errors. It contains no game data, formula,
Package resolver, filesystem access, or source-writing implementation.

`results.present` can reference only a calculation handle produced for the current
contribution; Kirin Tor renders that result in a host-owned slot and marks it stale when
the model revision changes. `storage` is a bounded, user-local, per-workspace preference
namespace declared by the Plugin manifest. `proposals.submit` queues one validated
all-or-nothing document transaction for explicit review; acceptance creates ordinary
unsaved Workbench drafts and never writes source directly.

Do not edit generated files directly. Change `src/kirin_tor/plugin_protocol.py` or its artifact
renderer, then run:

```bash
python scripts/generate_plugin_protocol.py
python scripts/generate_plugin_protocol.py --check
```
