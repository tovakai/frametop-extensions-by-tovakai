# Frametop Extension Manager v0.1.0 (experimental)

A **standalone settings application**, NOT part of the Frametop core.
The fork stays upstream + generic extension API.

## Install on Steam Frame

From your existing authenticated clone:

```sh
cd ~/frametop-extensions
git pull --ff-only
bash apps/extension-manager/install.sh install
```

Open **Frametop Extensions** in Plasma's application launcher, under Settings.
Or launch manually:

```sh
bash ~/frametop-extensions/apps/extension-manager/launch.sh
```

The launch script reuses upstream's active Frametop distrobox container if
host PySide6 is unavailable. No root, system changes, or core edits.

## GUI sections

- **Browse**: catalog, installed version, API compatibility, install/update
  confirmation and dependency preview.
- **Installed**: manager-installed snapshots, remove, or selection state.
  In v0.1 the **Enabled flag is metadata only; it does not start a plugin**.
- **Repositories**: your existing Tovakai checkout is the built-in source.
  Add GitHub repositories by HTTPS or SSH; refresh explicitly pulls with
  Git's normal configuration, including your local SSH deploy-key setup.

The manager does not silently fetch, install or start plugins during startup.

## CLI recovery

```sh
cd ~/frametop-extensions
python3 apps/extension-manager/manager.py catalog
python3 apps/extension-manager/manager.py sources
python3 apps/extension-manager/manager.py installed
python3 apps/extension-manager/manager.py plan tovakai.spatial-profiles
python3 apps/extension-manager/manager.py install tovakai.spatial-profiles
python3 apps/extension-manager/manager.py uninstall tovakai.spatial-profiles
python3 apps/extension-manager/manager.py refresh tovakai
```

### Files

- Config: ~/.config/frametop/extension-manager.json
- Additional Git sources: ~/.local/share/frametop/extension-manager/sources/
- Installed snapshots: ~/.local/share/frametop/extensions/<id>/

Plugins are copied with their source SDK, preserving relative imports.
Existing manually cloned/running plugins are not claimed or modified.
Plugins are only **staged for use**, not started. No systemd services,
plugin entrypoints, install hooks or uninstall hooks are executed.
Installation metadata is private and atomic; updates preserve the previous
snapshot until replacement is successful.

### Additional source repositories

Use repositories with the convention plugins/<slug>/extension.json.
Only github.com HTTPS and SSH URLs are accepted initially.
You must trust the source maintainer before using installed code.
Installation **is not a sandbox**. The manager does not execute untrusted code
while scanning or installing, rejects symlinks and unsafe paths, and refuses
conflicting source IDs. Optional manifest field "dependencies" lists other
extension IDs and is shown in the install confirmation.

### Uninstall app

```sh
bash apps/extension-manager/install.sh uninstall
```

Removes the manager's .desktop entry only. Existing installed plugin files
and source catalogs are deliberately retained.

### Tests

```sh
python3 -m unittest discover -s tests -v
```

Offline unit tests and CI cannot validate Kirigami rendering on Steam Frame.
The first live GUI test is still needed.
