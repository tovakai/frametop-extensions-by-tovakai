# Extension manifest convention (draft 1)

This is a **repository convention** for metadata, not an upstream-supported plugin registry. The independently installed experimental manager uses this convention; it may evolve.

```json
{
  "manifest_version": 1,
  "id": "tovakai.spatial-profiles",
  "name": "Spatial Profiles",
  "version": "0.0.1",
  "description": "Six-slot, spatial-only profile switching",
  "status": "prototype",
  "min_extension_api": 1,
  "required_capabilities": [],
  "optional_capabilities": ["screen.status", "screen.move", "screen.opacity"],
  "entrypoint": "profiles.py",
  "dependencies": []
}
```

Identifiers are lowercase, dot-separated namespaced components. Version is numeric major.minor.patch. Status is one of `planned`, `prototype`, `experimental`, `stable`. Entry point is a **relative file path inside the extension directory**, not a shell command, and is only informative at this stage. Capability strings are untrusted metadata until the extension checks the live compositor itself.

The SDK's discovery API validates manifests and never executes an entrypoint. No extension is auto-started. The standalone Extension Manager also accepts an optional `dependencies` array of namespaced plugin IDs. Dependencies are ordered and included in the user-confirmed installation plan, but do **not** start processes automatically. V1 `enabled` state is configuration metadata, not execution or a systemd service.
