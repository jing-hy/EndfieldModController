"""状态快照：把"此刻到底是什么环境"完整记下来，出问题时能逐项对比。

**为什么需要**（2026-10-01 的教训）：排查一个 bug 期间环境被改了多处，之后用户每一次
"还是不行"都不再是同一条件下的复现，反馈就不可比了 —— 用户原话：「**每次推 github
都要做快照**」。所以现在**推 main 之前会自动跑一次**（见 `scripts/push.py`），
把"这一版发布时的环境指纹"留档。

**快照里有什么**：
* `git` 状态：HEAD hash、分支、工作区是否 dirty、`git status --short` 的前若干行；
* **exe / addon 的 sha256** 与字节数（本地 vs modtest）；
* **modtest（数据根）**的关键文件：`config.json`、EFMI 的 `d3dx.ini` / `d3dx_user.ini` /
  staging 里被锁键改写过的 Mod ini、面板的 `controller.ini` / `actions.tsv` / `panel_info.txt`、
  `ReShade.ini` / `ReShadePreset.ini`、`_state/`；
* **游戏目录**：完整文件清单（相对路径 + 大小 + 修改时间），以及注入类小文件的副本；
* 关键配置项（哪些开关开着、库里有几个 Mod、勾选了哪些）。

**体积控制**：**只复制小文件**（默认 < 2 MB），大文件（如 exe）只记 sha256 —— 一次快照约几十 MB。
`--keep N`（默认 10）只保留最近 N 份快照，更旧的会被删除；删除范围**严格限定**在本脚本
自己创建的 `_snapshot_*` 目录内。

用法：
    python scripts/snapshot.py                     # 自动按时间戳命名
    python scripts/snapshot.py --label 0.9.1       # 带上版本号，便于回溯
    python scripts/snapshot.py --keep 5 --quiet
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = ROOT.parent / "modtest"          # exe 放哪，数据根就在哪
SNAPSHOT_PARENT = ROOT.parent                        # 与 _tmp / _backup_* 平级，**在仓库之外**
SIZE_LIMIT = 2 * 1024 * 1024                         # 超过就只记 hash，不复制

# 数据根里值得复制的小文件（相对路径）
DATAROOT_FILES = (
    "config.json",
    "runtime/dlss5/ReShade.ini",
    "runtime/dlss5/ReShadePreset.ini",
    "runtime/dlss5/panel_info.txt",
    "runtime/dlss5/user_ini_path.txt",
    "runtime/dlss5/actions.tsv",
    "runtime/dlss5/endfieldmodcontroller.addon64",
    "runtime/dlss5/modecontroller.addon.log",
    "runtime/builtin/XXMI/EFMI/d3dx.ini",
    "runtime/builtin/XXMI/EFMI/d3dx_user.ini",
    "runtime/builtin/XXMI/EFMI/Mods/MC_Controller/controller.ini",
    "runtime/builtin/XXMI/EFMI/Mods/MC_Controller/actions.tsv",
    "runtime/builtin/XXMI/EFMI/Mods/MC_Probe.ini",
    "runtime/builtin/XXMI/EFMI/Mods/EndfieldModControllerManaged/active_targets.json",
)
# 这些目录里的 ini/json 逐个记录 hash 并复制
MOD_INI_DIRS = ("runtime/builtin/XXMI/EFMI/Mods",)
# 游戏目录里值得复制的（注入类 / 配置类）小文件后缀
GAME_KEEP_SUFFIX = (".dll", ".ini", ".json", ".txt", ".bak", ".disabled", ".log")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30)
        return (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def git_state() -> dict[str, Any]:
    return {
        "head": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "last_commits": _git("log", "--oneline", "-5").splitlines(),
        "dirty_files": [l for l in _git("status", "--short").splitlines() if l.strip()][:40],
    }


def walk_listing(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            out.append({
                "rel": str(p.relative_to(root)).replace("\\", "/"),
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            })
    return out


class Snapshot:
    def __init__(self, label: str = "", *, data_root: Path = DEFAULT_DATA_ROOT,
                 out_parent: Path = SNAPSHOT_PARENT, quiet: bool = False) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"_snapshot_{label}-{stamp}" if label else f"_snapshot_{stamp}"
        self.dir = out_parent / name
        self.files = self.dir / "files"
        self.data_root = data_root
        self.quiet = quiet
        self.manifest: dict[str, Any] = {
            "at": stamp, "label": label, "generated_by": "scripts/snapshot.py",
            "hashes": {}, "copied": [], "game_files": [], "data_root_listing": [],
        }

    def log(self, msg: str) -> None:
        if not self.quiet:
            print(msg, flush=True)

    def copy(self, src: Path, rel: str) -> None:
        if not src.is_file():
            return
        try:
            size = src.stat().st_size
        except OSError:
            return
        self.manifest["hashes"][rel] = sha256_of(src)
        if size > SIZE_LIMIT:
            self.manifest["copied"].append(f"{rel}  ({size:,} B) —— 仅记 hash（超过 {SIZE_LIMIT // 1024 // 1024} MB）")
            return
        dst = self.files / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
            self.manifest["copied"].append(f"{rel}  ({size:,} B)")
        except OSError as exc:
            self.manifest["copied"].append(f"!! {rel}: {exc}")

    def run(self) -> Path:
        self.files.mkdir(parents=True, exist_ok=True)
        self.manifest["git"] = git_state()
        self.manifest["versions"] = {
            "version_py": (ROOT / "endfieldmodcontroller" / "version.py").read_text(encoding="utf-8").split('"')[1]
            if (ROOT / "endfieldmodcontroller" / "version.py").is_file() else "",
        }
        self.log(f"[1/4] git: {self.manifest['git']['head'][:12]} "
                 f"({self.manifest['git']['branch']}) 未提交 {len(self.manifest['git']['dirty_files'])} 项")

        # 本地产物
        for rel in ("dist/EndfieldModController.exe", "assets/addon/endfieldmodcontroller.addon64"):
            self.copy(ROOT / rel, "local/" + rel)

        # 数据根（modtest）
        root = self.data_root
        if root.is_dir():
            for p in root.glob("*.exe"):
                self.copy(p, f"modtest/{p.name}")
            for rel in DATAROOT_FILES:
                self.copy(root / rel, "modtest/" + rel)
            for sub in MOD_INI_DIRS:
                d = root / sub
                if d.is_dir():
                    for p in d.rglob("*.ini"):
                        try:
                            if p.stat().st_size <= SIZE_LIMIT:
                                self.copy(p, "modtest/" + str(p.relative_to(root)).replace("\\", "/"))
                        except OSError:
                            continue
            self.manifest["data_root_listing"] = walk_listing(root / "runtime") if (root / "runtime").is_dir() else []
            lib = root / "library"
            self.manifest["library"] = sorted(p.name for p in lib.iterdir()) if lib.is_dir() else []
            cfg_path = root / "config.json"
            if cfg_path.is_file():
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    self.manifest["config_keys"] = {
                        k: cfg.get(k) for k in (
                            "selected_mods", "hotkey_takeover", "dlss5_addon_enabled", "firstperson_addon_enabled",
                            "efmi_injection", "secondary_motion_injection", "poser_injection", "reshade_injection",
                            "use_builtin_runtime", "game_exe", "xxmi_launcher", "staging_mods_dir", "library_dir",
                        ) if k in cfg
                    }
                except (OSError, ValueError):
                    pass
            self.log(f"[2/4] 数据根 {root.name}：库内 {len(self.manifest.get('library', []))} 个 Mod，"
                     f"清单 {len(self.manifest['data_root_listing'])} 项")
        else:
            self.log(f"[2/4] !! 数据根不存在：{root}")

        # 游戏目录（只记清单 + 复制注入类小文件）
        game = None
        game_exe = str(self.manifest.get("config_keys", {}).get("game_exe") or "")
        if game_exe:
            game = Path(game_exe).parent
        if game and game.is_dir():
            self.manifest["game_dir"] = str(game)
            self.manifest["game_files"] = walk_listing(game)
            for p in game.rglob("*"):
                if not p.is_file():
                    continue
                try:
                    if p.stat().st_size > SIZE_LIMIT:
                        continue
                except OSError:
                    continue
                rel = str(p.relative_to(game)).replace("\\", "/")
                low = rel.lower()
                interesting = (
                    (p.parent == game and (p.suffix.lower() in GAME_KEEP_SUFFIX or low.startswith("nvngx")))
                    or low.startswith(("plugin/", "secondarymotion/"))
                    or "reshade" in low or "d3dx" in low
                )
                if interesting:
                    self.copy(p, "game/" + rel)
            self.log(f"[3/4] 游戏目录 {game}：清单 {len(self.manifest['game_files'])} 项")
        else:
            self.log(f"[3/4] !! 没定位到游戏目录（config.game_exe={game_exe or '空'}）")

        (self.dir / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log(f"[4/4] 快照完成：{self.dir}（复制 {len(self.manifest['copied'])} 个文件）")
        return self.dir


def prune(keep: int, parent: Path = SNAPSHOT_PARENT, *, quiet: bool = False) -> list[str]:
    """只保留最近 `keep` 份快照。**只动本脚本自己创建的 `_snapshot_*` 目录**，别的一律不碰。"""
    if keep <= 0:
        return []
    snaps = sorted((p for p in parent.glob("_snapshot_*") if p.is_dir()),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    removed: list[str] = []
    for old in snaps[keep:]:
        try:
            shutil.rmtree(old)
            removed.append(old.name)
        except OSError:
            continue
    if removed and not quiet:
        print(f"      已清理 {len(removed)} 份旧快照（保留最近 {keep} 份）：{', '.join(removed)}", flush=True)
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="给当前状态做一份快照（推 main 前自动执行）")
    ap.add_argument("--label", default="", help="标签，通常传版本号，如 0.9.1")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT), help="数据根（默认 ../modtest）")
    ap.add_argument("--out", default=str(SNAPSHOT_PARENT), help="快照存放目录（默认工作区上级）")
    ap.add_argument("--keep", type=int, default=10, help="保留最近几份（默认 10，0 = 不清理）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    snap = Snapshot(args.label, data_root=Path(args.data_root), out_parent=Path(args.out), quiet=args.quiet)
    path = snap.run()
    prune(args.keep, Path(args.out), quiet=args.quiet)
    if not args.quiet:
        print(f"SNAPSHOT={path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
