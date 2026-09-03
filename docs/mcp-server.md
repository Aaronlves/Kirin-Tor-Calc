# MCP server

`kt mcp [WORKSPACE]` exposes one existing Kirin Tor workspace to an MCP host over stdio. The
adapter is intentionally thin: it reuses the same workspace loader, validator, engine, authoring
contract, Package resolution, and atomic source writer as the CLI and Workbench. It does not create
another document model or retain Agent state.

An MCP host can launch it with a configuration equivalent to:

```json
{
  "mcpServers": {
    "kirin-tor": {
      "command": "kt",
      "args": ["mcp", "/absolute/path/to/workspace"]
    }
  }
}
```

If `WORKSPACE` is omitted, Kirin Tor discovers the workspace from the server process's current
directory. The configured path may also be a file or nested directory inside the workspace. The
server uses the official MCP Python SDK v2 stdio transport. New clients negotiate the MCP
`2026-07-28` protocol; the SDK also handles its supported legacy initialization flow. Standard error
is reserved for operator diagnostics; standard output never contains banners, prompts, or
non-protocol text.

## Resources

| URI | Content |
| --- | --- |
| `kirin://workspace/manifest` | Current workspace path, local-source revision, document catalog, read-only flags, Package provenance, and source hashes |
| `kirin://workspace/index` | Validated targets, inputs, presets, charts, analyses, and document IDs; unavailable while the workspace is invalid |
| `kirin://language/authoring-contract` | Versioned public vocabulary, snippets, signatures, runtime symbols, and syntax-reference identities used by the editor |
| `kirin://source/…` | One complete local or locked-Package `.kirin` source; discover the encoded URI through `resources/list` rather than constructing it |

Each source resource carries its stable workspace key, current SHA-256 digest, read-only status, and
limited Package identity in `_meta.kirinTor`. Resource listings are snapshots, and clients should
list them again after a successful write. The server does not claim resource subscriptions or
list-changed notifications.

## Tools

| Tool | Effect |
| --- | --- |
| `kirin_check` | Validates the current durable workspace and locked Package sources |
| `kirin_validate_source` | Validates one complete `entries/**/*.kirin` proposal as an in-memory overlay and writes nothing |
| `kirin_evaluate` | Evaluates one static `ENTRY.OUTPUT` using exact Kirin semantics, optional preset, and exact string overrides |
| `kirin_explain` | Returns a target's expanded expression, inputs, retained conditions, units, and dependencies |
| `kirin_analyze` | Executes one named bounded `ENTRY.ANALYSIS`; trace details are omitted by default and no run record or artifact is written |
| `kirin_apply_source` | Validates the whole candidate workspace, checks the expected source hash, then atomically creates or replaces one local source |

`kirin_apply_source` requires `expected_sha256`. For an existing document, use the digest returned by
the latest manifest or source resource. The empty string means that the path is expected not to
exist and is accepted only for creation. A stale digest, an invalid workspace, a path outside
`entries/`, or a locked Package path fails without writing. `kirin_analyze` accepts
`include_trace: true` when the complete event trace is needed; its default compact result still
retains Measures, proof metadata, strategies, bounds, and exact outputs. The MCP surface
intentionally provides no delete, rename, Package installation, Plugin control, artifact export,
run-record creation, shell execution, or arbitrary filesystem tool.

Tool failures are returned as MCP tool results with `isError: true` and Kirin Tor's stable structured
error code and location fields. Malformed protocol requests, unknown tools, invalid tool arguments,
and unknown resources use JSON-RPC errors.

## Authority and collaboration boundary

Durable `entries/**/*.kirin` files remain the only writable model authority. Resources, indexes,
tool results, and the authoring contract are read models. The MCP server does not read or mutate
browser-unsaved buffers, recovery state, prompts, transcripts, or Agent activity. If the Workbench
has a dirty buffer when MCP changes its disk source, the normal base/draft/disk conflict flow applies.

The MCP adapter serializes each tool call within its process, but it is not a cross-process lock.
The expected hash prevents silently overwriting a source changed by another writer between reads.
One call changes at most one source; an Agent that needs a coherent multi-document cutover must still
provide its own atomic write discipline or use another explicitly designed transaction boundary.
