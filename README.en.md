<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<div align="center">

<h1>EndfieldModController</h1>

<p>An all-in-one mod manager for <b>Arknights: Endfield</b> — one click brings <b>DLSS5 neural rendering +
first-person view + outfit mods + physics + posing / MMD playback</b> together, with the runtime installed
from scratch and <b>zero configuration to get started</b>.</p>

<p>
  <a href="https://www.python.org/"><img alt="Python 3" src="https://img.shields.io/badge/Python-3-3776AB?logo=python&amp;logoColor=white"></a>
  <a href="https://learn.microsoft.com/windows/"><img alt="Windows 10 / 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&amp;logoColor=white"></a>
  <a href="https://github.com/jing-hy/EndfieldModController/releases"><img alt="Latest release" src="https://img.shields.io/github/v/release/jing-hy/EndfieldModController?label=Release&amp;color=f0b429&amp;logo=github"></a>
  <a href="LICENSE"><img alt="AGPL-3.0-only license" src="https://img.shields.io/github/license/jing-hy/EndfieldModController?label=License&amp;color=3DA639"></a>
</p>

<p>Windows desktop app, single exe. Current version <b>1.6.0</b> — <a href="https://github.com/jing-hy/EndfieldModController/releases">download the latest release</a></p>

<p>🌐 <a href="README.md">中文</a> | English</p>

<p>📖 Install, pages and troubleshooting → <b><a href="docs/README.detailed.md">Detailed docs</a></b><br>
🆕 What changed in this release → <b><a href="RELEASE_NOTES.md">Release notes</a></b><br>
🛠 Want to work on the code / open a PR → <b><a href="CONTRIBUTING.md">Contributor guide</a></b></p>

</div>

---

## Highlights

- **One-click launch**: completes the runtime → maintains the injection library → runs self-checks → starts the injector. Missing pieces are fetched automatically, and progress is visible.
- **Mod library**: drop archives to import, with automatic character detection (Chinese names, nicknames, English codenames and pinyin), one mod per character to avoid crashes, and append-only full backups of newly imported mods.
- **Mod store + downloads**: browse / search GameBanana, view details and download in one click; downloads run in the background, can be appended, and are imported automatically.
- **In-game unified panel**: press `Home` in game → the ModeController page. When several mods fight over the same key, clicking the panel presses the right one (Universal only).
- **Crash attribution & game-folder cleanup**: crashes are attributed to resource conflicts or other causes; third-party injections in the game folder are backed up before being moved away, and can be restored with one click.
- **Hands-off**: the game itself, mods and third-party components are never modified; config and data live next to the exe — copy the folder to move machines.
- **Two editions**: **Universal** (DLSS5 + first-person + outfit mods) and **Lite** (no ReShade at all — outfit mods / jiggle / posing / store only); both can share one folder and be swapped anytime.

## Which edition?

| Your case | Pick |
| --- | --- |
| You want **DLSS5 neural rendering / super resolution**, first-person view, or the in-game unified panel | **Universal** `EndfieldModController.exe` |
| You only use **outfit mods** (+ jiggle / posing / store downloads) and would rather keep ReShade out of the game | **Lite** `EndfieldModController-Lite.exe` |
| The game crashes on launch, you got an anti-cheat warning, or you want to rule ReShade out first | **Lite** (no ReShade at all: never downloaded, installed or injected; ReShade leftovers already in the game folder are moved away with backups and can be restored) |
| Not sure | Start with **Universal**; switch to Lite whenever you like |

Both editions **share one data root** (`config.json` / `runtime\` / `library\`) — keep both exes in the same folder and swap freely; your mod library, backups and download history carry over.

## Getting started

1. Download the exe from [Releases](https://github.com/jing-hy/EndfieldModController/releases): `EndfieldModController.exe` (Universal) or `EndfieldModController-Lite.exe` (Lite).
2. Put it in a **normal writable folder** (not `Program Files`, not a temp folder) and double-click.
3. Click **Launch**. The first run installs the runtime; if it asks you to click again, do so.

Then start the game: in Universal, DLSS5 needs no manual setup — check that "successful NR frames" in the ReShade panel is counting up. Lite has no DLSS5; outfit mods work directly. A step-by-step tour runs on first launch.

## Day to day

- **Mod library**: drop archives → enable cards (one per character) → **Generate controller**.
- **Store / downloads**: browse the store, queue downloads; they run in the background and finished imports land under **Downloaded**.
- **Launch**: the big **Launch** button, plugin toggles and the runtime log.
- **Settings** (gear at the bottom-left): General / Appearance / Paths / Downloads / Web service / Maintenance / Debug / About; the language switch (中文 / English) is under General.

## FAQ

**Q: The DLSS5 switch is off by default / won't turn on?** It needs **RTX 20 series or newer** (no tensor cores = it cannot render a frame, so the app disables it). RTX 20/30/40/50 get the matching runtime automatically.

**Q: The game crashes / closes while loading?** The app produces a crash bundle with attribution: for mod resource conflicts it lists the two mods — disable one and relaunch; for other causes, attach the bundle to an issue.

**Q: Many mods installed but nothing changes in game?** Check the relevant toggles (outfit / physics / DLSS5 are independent); only one mod per character is kept — select it and click **Generate controller**.

**Q: Self-check keeps reporting missing files?** Your antivirus is likely quarantining them; the dialog names the file and the folder to whitelist.

**Q: I already have my own injector environment?** Point Settings → Paths at it and disable "use built-in runtime".

## Third-party components & license

This project only **distributes and orchestrates** components without modifying them: XXMI Launcher / XXMI Libraries / EFMI (MIT), 3DMigoto (MIT), ReShade (BSD-3, Universal only), RenoDX / Endfield Enhancer (MIT), iMMERSE (MIT), SecondaryMotion, Endfield Poser (AGPL-3.0, not shipped in Releases), NVIDIA NGX runtimes and community DLSS NR variants — see the [detailed docs](docs/README.detailed.md).

This project itself is **AGPL-3.0-only** (see [LICENSE](LICENSE)). Copyright (c) 2026 jing-hy.

## Disclaimer

- Not an official tool; not affiliated with Hypergryph.
- Using mods may violate the game's terms of service — **you take the risk**.
- Only injection files in the game folder are touched, always with a backup and one-click restore; the game itself, assets and saves are never modified.

## Feedback

Settings → Maintenance → "Export diagnostics" bundles logs and device info. Report via [Issues](https://github.com/jing-hy/EndfieldModController/issues) or the QQ group **1045239747** (verification answer **jing_hy**). Please include the **symptoms**.

---

> Install steps, directory layout, troubleshooting → **[detailed docs](docs/README.detailed.md)**　|　中文 → **[README.md](README.md)**　|　Full change list → **[RELEASE_NOTES.md](RELEASE_NOTES.md)**
