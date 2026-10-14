# Frametop Extensions by tovakai

Optional extensions for [Frametop](https://github.com/Frametop/frametop), developed independently from the compositor.

This repository will house **Spatial Profiles**, **Spatial Follow**, **Gaze Attention**, **Spatial Toolbar**, and **Spatial Instruments**. It is separate from [the minimal Frametop extension API fork](https://github.com/tovakai/frametop/tree/rebuild/extension-api) and the [legacy implementation](https://github.com/tovakai/frametop/tree/legacy).

> **Early development.** Frametop extension API v1 discovery and opacity control have been verified on a Steam Frame. Spatial Profiles v0.1.0 now supports CLI capture and switching of **world-anchored** layouts, with device validation of those operations still pending. There is no plugin installer/manager or full legacy feature parity yet.

## Extension Manager (experimental)

The independently installed **Frametop Extensions** settings app browses our
built-in repository, adds third-party GitHub sources, and stages reviewed plugin
snapshots without touching Frametop core. It has a Kirigami interface plus
a standard-library CLI fallback. No downloaded entrypoint auto-executes.

On Steam Frame, from your authenticated extensions checkout:

```sh
cd ~/frametop-extensions
git pull --ff-only
bash apps/extension-manager/install.sh install
```

Open **Frametop Extensions** under Settings, or run
`bash apps/extension-manager/launch.sh`.

See the [Extension Manager guide](apps/extension-manager/README.md) for safety,
repository authentication, removing the app and current limitations. The
GUI's first Steam Frame hardware test is pending.

## Layout

- `apps/extension-manager/`: independent settings application and metadata-first plugin manager.
- `sdk/frametop_ext/`: standard-library Python client for Frametop's versioned extension commands.
- `plugins/spatial-profiles/`: **v0.1.0 experimental**: independent world-anchored spatial profiles with native 450 ms transitions, six slots and read-only inspection of legacy profiles.
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

## First extension: Spatial Profiles

On an API-enabled Frame with the Frametop desktop running:

```sh
python3 plugins/spatial-profiles/profiles.py check-api
python3 plugins/spatial-profiles/profiles.py save "Desk"
# Reposition your screens in VR, then:
python3 plugins/spatial-profiles/profiles.py save "Reading"
python3 plugins/spatial-profiles/profiles.py switch "Desk"
python3 plugins/spatial-profiles/profiles.py slot 1 "Desk"
python3 plugins/spatial-profiles/profiles.py use-slot 1
```

New profiles are stored in `~/.config/frametop-extensions/spatial-profiles.json` and **do not overwrite** upstream or legacy Frametop layouts. See [Spatial Profiles usage and limitations](plugins/spatial-profiles/README.md) before testing.

## Developer check

```sh
python3 -m unittest discover -s tests -v
```

No Steam Frame required. Live tests must be performed separately and explicitly.
