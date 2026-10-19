# Architecture and boundaries

## Two codebases, one contract

Frametop fork (`tovakai/frametop`, branch `rebuild/extension-api`) owns the generic compositor and extension transport. This repository owns **optional** user-facing spatial features. The old fork remains available at `legacy` for reference and behavioral regression tests.

The extension API draft v1 uses Frametop's existing abstract UNIX datagram control socket (`@ft_screens`). Extensions discover its version and capabilities. Initial capabilities: `screen.status`, `screen.opacity` and `screen.move`. A companion Python SDK lives in `sdk/frametop_ext`.

There is **no dynamic plugin loader or stable external event stream yet**. The optional Extension Manager is a separately installed Kirigami settings app. It can browse GitHub sources and stage/copy individual extension snapshots, but manifest discovery and installation never execute plugin entrypoints; managed `enabled` state is metadata only. The manager does not run a plugin lifecycle service yet.

## Planned separation

- Spatial Profiles: the authority for *spatial* arrangement, profile slots and 450 ms transitions. Do not launch/close applications when switching spatial profiles. Preserve same-screen-count semantics.
- Spatial Follow: compositor-tick-aware head-soft, head-rigid, yaw and position follow, dead zone and lag. Needs a generic follow/motion API; external 90 Hz command spam is not acceptable.
- Gaze Attention: alpha transitions and attention targeting, reusing upstream's gaze system. Requires an independent read-only gaze-target feed; must not enable gaze-to-pointer as a side effect.
- Spatial Toolbar: independent OpenVR UI overlay, with start/tasks/display/tray adapters. Screen docking must be implemented against generic attachment hooks, not private compositor objects.
- Spatial Instruments: composable widgets with the same anchor and attention contracts; restore them only after follow and gaze primitives are validated.
- Frame Depth: offline SBS prototype. Live depth-aware stereo will require generic frame/effect APIs and arbitration with the core hand-cutout stereo pipeline. No renderer hook or startup lifecycle exists in v1; see `plugins/frame-depth/LIVE-INTEGRATION.md`.

## Extension convention (draft)

Each extension may live in `plugins/<slug>/` and declares `extension.json` ([schema](extension-manifest-v1.md)). The SDK must treat capability negotiation as mandatory. The manifest should remain declarative: no executing arbitrary scripts merely by discovering an extension.

A future manager may install optional extensions into `~/.local/share/frametop/extensions/<id>/`, place per-extension configuration in `~/.config/frametop/extensions/<id>/`, and manage opt-in user services; these are **proposals**, not behavior currently implemented.

## Compatibility gates

1. Offline unit tests for schema and API contract.
2. Build the core compositor and run on Steam Frame: verify no overlay/input regressions.
3. Test profile transition, pin, scaling and click-through on device.
4. Uninstall each extension without changing other extensions or the desktop.
5. Verify upstream sync doesn't break the contract.

Never overwrite `~/.config/frametop-layout-profiles.json` on first run. Legacy data is read-only until the user explicitly opts into a migration.

## Independent extension manager

The self-contained app in `apps/extension-manager/` installs its own application menu entry; it never edits Frametop core or its session. Its default catalog is the current `frametop-extensions-by-tovakai` checkout. Additional GitHub repos are cloned only after explicit user action. Installed packages are independent, versioned snapshots in `~/.local/share/frametop/extensions/<id>/`. The manager reuses existing Frametop Kirigami dependencies through `scripts/in-box` without changing core. Its CLI works without Qt. Live GUI hardware validation is pending.
