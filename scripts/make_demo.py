"""Create a tiny demo library so the UI can be tested without real mods.

⚠️⚠️ **绝不许动仓库里的真实 `library\`**（2026-10-04 修）：
用户定的硬规则是「**任何情况都不要动用户的 mod 库**」（唯一允许的删除入口是界面上
「移出 Mod 库」，移进 `runtime\backups\mod-trash` 可找回）。而这个脚本原先第一件事就是
`shutil.rmtree(ROOT / "library")` —— 对着真实工作区跑一次，**用户的整库就被删掉换成
3 个 demo ini**，既无确认也无备份。它在 `scripts\` 里和其它构建脚本并排，极易被顺手执行。

现在：
  * 默认写到 `<工作区>\\_tmp\\demo-library`（不碰真实库，`_tmp/` 已被 gitignore）；
  * 想写别处必须显式 `--out <目录>`，且**拒绝**目标是真实 Mod 库或其上级/子目录
    （判据用 `fsutil.library_conflict`，与主程序的护栏同一份实现）；
  * 目标目录已存在且非空时**不再 rmtree**，改为提示并退出（要重建请自己先删）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "_tmp" / "demo-library"
REAL_LIBRARY = ROOT / "library"

SUMMER = """\
; demo summer outfit
namespace = ChenSummer

[Constants]
global persist $cape = 0
global persist $bag = 1

[KeyCape]
key = no_modifiers VK_9
type = cycle
$cape = 0,1

[KeyBag]
key = no_modifiers VK_8
run = CommandListToggleBag
"""

HALLOWEEN = """\
; demo halloween outfit
namespace = ChenHalloween

[Constants]
global persist $hat = 0

[KeyHat]
key = no_modifiers VK_7
type = cycle
$hat = 0,1
"""

DEP = """\
; demo dependency
[Constants]
global persist $enabled = 1
"""


def write(lib: Path, rel: str, text: str) -> None:
    path = lib / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _refuse(reason: str) -> int:
    print(f"!! 拒绝执行：{reason}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成演示用的迷你 Mod 库")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help=f"输出目录（默认 {DEFAULT_OUT}）")
    args = parser.parse_args(argv)
    lib = Path(args.out).expanduser().resolve()

    # 护栏：绝不写真实 Mod 库（以及它的上级/子目录）
    try:
        sys.path.insert(0, str(ROOT))
        from endfieldmodcontroller import fsutil
    except Exception:  # noqa: BLE001 —— 连包都 import 不了时用最保守的判据
        if lib == REAL_LIBRARY.resolve() or REAL_LIBRARY.resolve() in lib.parents:
            return _refuse(f"{lib} 是（或位于）真实 Mod 库 {REAL_LIBRARY} 里")
    else:
        conflict = fsutil.library_conflict(REAL_LIBRARY, lib)
        if conflict:
            return _refuse(conflict)

    if lib.exists() and any(lib.iterdir()):
        return _refuse(f"{lib} 已存在且非空 —— 要重建请先自己删掉它（本脚本不再自动 rmtree）")

    write(lib, "陈/夏日泳装/mod.ini", SUMMER)
    write(lib, "陈/万圣节/mod.ini", HALLOWEEN)
    write(lib, "_deps/RabbitFX/mod.ini", DEP)
    print(f"demo library created: {lib}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
