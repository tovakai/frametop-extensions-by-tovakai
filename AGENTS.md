# Contributor guidance

- This repository holds **optional Frametop extensions**. Do not vendor or modify the Frametop compositor here.
- Frametop core extension contract: https://github.com/tovakai/frametop/tree/rebuild/extension-api (draft). Original implementation: https://github.com/tovakai/frametop/tree/legacy.
- Preserve the six-slot spatial-profile model, head-relative placement, fade/attention metadata, instruments, dock settings, and 450 ms default transition. Do not silently substitute upstream's app/session profiles.
- Extension install/uninstall must affect only extension-owned paths. No unsolicited SteamVR files, boot settings, system services, or user layout changes.
- Fail closed when an extension API capability is missing. Do not overwrite profiles to "migrate" them. Do not execute downloaded plugin manifests.
- Python standard library for baseline SDK; tests run without a headset using mocks.
- Prefer standalone extension packages with explicit manifests and a common SDK over copying Frametop C++ code into plugins.
- An extension's capability claims must describe only implemented features; never mark work as device-tested without live verification.
