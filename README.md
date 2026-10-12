# Frametop Extensions by tovakai

Optional extensions for [Frametop](https://github.com/Frametop/frametop), developed independently from the compositor.

This repository will house **Spatial Profiles**, **Spatial Follow**, **Gaze Attention**, **Spatial Toolbar**, and **Spatial Instruments**. It is separate from [the minimal Frametop extension API fork](https://github.com/tovakai/frametop/tree/rebuild/extension-api) and the [legacy implementation](https://github.com/tovakai/frametop/tree/legacy).

> **Early development.** The Frametop extension API is currently an unmerged, device-untested draft. Nothing here is an installable end-user plugin or a replacement for the working legacy fork yet.

## Layout

- `sdk/frametop_ext/`: standard-library Python client for Frametop's versioned extension commands.
- `plugins/spatial-profiles/`: first extension, beginning with read-only compatibility inspection of the original spatial profiles.
- `plugins/spatial-follow/`, `plugins/gaze-attention/`, `plugins/spatial-toolbar/`, `plugins/spatial-instruments/`: future extension specifications.
- `docs/`: boundaries, manifest conventions and compatibility policy.
- `tests/`: offline tests without SteamVR or a headset.

## Principles

1. **Upstream-first.** The Frametop fork should contain only generic API hooks; feature logic lives here.
2. **Preserve the good stuff.** The legacy six-slot spatial profiles and 450 ms switching animations are the compatibility target, not upstream's app-session-oriented profiles.
3. **Install independently.** Each extension should eventually have its own version, lifecycle, configuration and tests, without editing core source files.
4. **No surprise mutations.** No installer or developer command should silently overwrite Frametop settings, SteamVR, or existing profiles.
5. **Honest capabilities.** An extension must check the compositor's reported API version and capabilities rather than guessing.

See [architecture](docs/architecture.md) and [manifest draft](docs/extension-manifest-v1.md).

## Developer check

```sh
python3 -m unittest discover -s tests -v
```

No Steam Frame required. Live tests must be performed separately and explicitly.
