# Spatial Profiles (first extension)

This is the **first migration target** from [legacy Frametop](https://github.com/tovakai/frametop/tree/legacy). We will preserve the spatial-only behavior, six profile slots, fixed screen count, follow/attention/instrument/toolbar metadata and **450 ms** profile transitions.

The original profiles live at `~/.config/frametop-layout-profiles.json`. This prototype **only reads** that file. It does not edit Frametop's active layout, spawn applications, install services or move screens.

```sh
python3 tools/list_extensions.py

python3 plugins/spatial-profiles/profiles.py list
python3 plugins/spatial-profiles/profiles.py show "Desk"
python3 plugins/spatial-profiles/profiles.py plan "Desk"
python3 plugins/spatial-profiles/profiles.py check-api

# Inspect an exported copy without using your live config:
python3 plugins/spatial-profiles/profiles.py --file /path/to/frametop-layout-profiles.json list --json
```

`plan` reports the fields we'd need for eventual full application and explicitly identifies missing compositor API capabilities. It doesn't silently downgrade follow modes or convert head-relative screen poses into wrong world coordinates.

The extension API v1 can animate world-space screen positions and opacity, but still cannot reproduce the full original profile behavior. **Do not call this plugin a replacement until the gaps are closed and verified on Steam Frame.**

## Next implementation milestones

1. Read-only inspector, metadata validation, SDK capability negotiation, offline tests.
2. Snapshot/capture and preview, including HMD-relative pose transforms.
3. Apply spatial position, curve, scale-independent width, hidden state, and opacity with rollback on partial errors.
4. Introduce generic follow and gaze-attention APIs, then restore anchors/attention semantics.
5. Restore profile slots, toolbar/instrument state, atomic save and migration with explicit opt-in.
6. Run live tests with SteamVR, controller clicks, gaze, performance and app persistence.
