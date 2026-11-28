<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# EndfieldModController — Detailed docs (English)

Current version **1.6.0** ｜ [Download](https://github.com/jing-hy/EndfieldModController/releases)

> This is the English condensed edition. The full, most up-to-date reference is the
> **[Chinese detailed docs](README.detailed.md)** (install steps, every page, directory layout, item-by-item troubleshooting).
> Quick start: **[README.en.md](../README.en.md)** ｜ 中文: **[README.md](../README.md)**

---

## 1. Install and first launch

### Download and placement

1. Download one of the two exes from [Releases](https://github.com/jing-hy/EndfieldModController/releases):
   - `EndfieldModController.exe` — **Universal** (DLSS5 + first-person + outfit mods);
   - `EndfieldModController-Lite.exe` — **Lite** (no ReShade at all; outfit mods / jiggle / posing / store only).
   Both can share one folder; config, library, backups and download history are shared.
   Lite never rewrites your ReShade switches — switching back restores them as-is.
2. Put it in a normal writable folder (**not** `Program Files`, not a temp folder). The app requests admin rights on launch.
3. Double-click and click **Launch**. The first run installs the runtime and may ask you to click Launch again.

### Upgrading from 1.5.1 or older

- In-app update: Settings → Maintenance → "Check for updates". The released 1.5.1 only matches the
  **unversioned `EndfieldModController.exe`** asset (release script enforces uploading it), so Universal users are
  never switched to Lite; from 1.5.2 each edition picks its own asset.
- Manual update: download the new exe over the old one — `config.json`, `runtime\` and `library\` stay untouched.
- After upgrading, old themes are migrated (amber/cyan/violet/emerald → dark + same accent), the character table is
  refreshed (male/female Endministrator cards), and new settings appear.
- **The local UI automation API is now off by default** — enable it in Settings → Web service if you used `ui_ctl.py`.

### What happens on first launch

The window appears quickly (loading page with steps), the runtime is installed with verification, and a step-by-step
tour highlights the next button. DLSS5 needs no manual setup: watch "successful NR frames" in the ReShade panel.

---

## 2. Pages

### Mod library

Drop `.zip` / `.7z` / `.rar` anywhere to import (extract → character detection → library). Cards can be toggled;
"⋯" lets you change the character, open the folder or remove the mod. One mod per character is enforced;
enable the ones you want and click **Generate controller**.

### Launch

The big **Launch** button plus plugin toggles (DLSS5 / first-person / outfit mods / physics / posing / unified panel)
and the runtime log. Launch = complete runtime → maintain injection library → self-checks → start the injector.

### Dependencies

Shows each component (green = present / red = missing), download speed and a live log; "Install missing" fixes gaps.
Offline machines can "Import dependency bundle…".

### Mod store

Browse GameBanana: categories / characters / search / sort; detail pages with large screenshots; one-click download.
- **Update index** rebuilds the local store index (the list and counts come from it).
- **Update all** checks installed mods for new versions and queues them; it scans first and reports when everything is up to date.
- The R18 tri-state (show / blur / hide) is remembered (stored in `config.json`).
- Switching pages while a detail page is loading keeps loading in the background and never pulls you back.

### Downloads

Parallel downloads with line fallback and resume; archives are extracted, imported and character-matched.
Downloads run in the background and can be appended. Finished imports move to the **Downloaded** card,
kept until the app restarts.

### Settings

The gear at the bottom-left opens an in-app window (left column = 8 quick-jump sections, right side = one scrollable page):
**General** (language: 中文 / English, launch behavior, log auto-cleanup, Universal-only ReShade/DLSS5 switches),
**Appearance** (light/dark background + separate accent color; custom background image and opacity),
**Paths** (workspace / library / backup / game & launcher / component dirs / runtime dirs),
**Downloads** (proxy, acceleration, lines, GitHub mirrors),
**Web service** (local UI automation API, **off by default**; toggle/port apply immediately),
**Maintenance** (runtime state, restore game, clear & re-download deps, rollback, component installs, diagnostics),
**Debug** (environment, open log/data/program folders, clean logs, detailed probes),
**About** (version & edition, license, project links, update check).
The **Help** button at the bottom-left of the window opens the manual inside the same dialog.

---

## 3. In-game unified panel (Universal only)

Mods bind different keys (`←`, `Ctrl+5`, `Alt 0`…), and several mods often fight over the same key.
With "Integrate mod hotkeys" enabled (default), press **`Home`** in game → **ModeController** page: each entry is a
button that presses that mod's own key once. It does not lock your keys, can adjust panel size (0.75×–2×, remembered)
and reset the layout. The panel log is available from the logs page.

---

## 4. Directory layout

```text
<folder with the exe>/
├─ config.json                  settings (atomic writes; broken files are quarantined)
├─ library/                     your mod library
├─ mod-backup/                  append-only mod backups (configurable in Settings)
└─ runtime/
   ├─ builtin/XXMI/             downloaded injector + injection library + outfit engine
   ├─ dlss5/                    DLSS5 base and add-ons (Universal)
   ├─ reshade/                  controller plug-ins and action list
   ├─ secondary_motion/         physics tool (optional)
   ├─ poser/                    posing/MMD package (optional)
   ├─ game_backup/<stamp>/      game-folder cleanup backups (restorable)
   ├─ backups/                  engine/config history backups
   ├─ logs/                     logs and diagnostic bundles
   └─ _update/                  self-update downloads and leftovers
```

`library\` and `mod-backup\` are **your data**; no automatic cleanup touches them.

---

## 5. Troubleshooting

### DLSS5

1. Check the startup log for self-check errors.
2. Make sure the in-game upscaler is **DLSS** (FSR/XeSS do not bind neural rendering).
3. Check the ReShade panel: "successful NR frames" should increase.
4. The DLSS5 toggle refuses to turn on without tensor cores (RTX 20 series or newer).

### Crashes and self-checks

- The app generates a crash bundle with attribution; resource conflicts list the offending mods.
- When key files keep disappearing, antivirus is usually quarantining them — the dialog names the file and the folder to whitelist.
- For rendering/API issues, use Settings → Debug → "Open log folder" / "Detailed probes".

### What the diagnostic bundle contains

`summary.txt` (including the edition: Universal or Lite), `logs/`, `player/Player.log`, ReShade/DLSS5 evidence,
`injection-trace.jsonl`, plus an environment report and a capture manifest. Export it from
Settings → Maintenance → "Export diagnostics".

---

## 6. Automation API

Settings → **Web service** → enable (off by default, port 0 = random). It binds `127.0.0.1` only and writes
`{url, port, token}` to `runtime\\_state\\ui_api.json`.

```text
python scripts\ui_ctl.py --state-file <data-root>\runtime\_state\ui_api.json state
python scripts\ui_ctl.py --state-file <data-root>\runtime\_state\ui_api.json tab store
```

The API is documented in [UI automation docs](ui-automation.md).

---

## 7. Feedback

Settings → Maintenance → "Export diagnostics" bundles logs + device info. Report via
[GitHub Issues](https://github.com/jing-hy/EndfieldModController/issues) or the QQ group **1045239747**
(verification answer **jing_hy**). Always include the symptoms (what you clicked, what you saw).
