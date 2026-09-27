"""Create a tiny demo library so the UI can be tested without real mods."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "library"

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


def write(rel: str, text: str) -> None:
    path = LIB / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if LIB.exists():
        shutil.rmtree(LIB)
    write("陈/夏日泳装/mod.ini", SUMMER)
    write("陈/万圣节/mod.ini", HALLOWEEN)
    write("_deps/RabbitFX/mod.ini", DEP)
    print(f"demo library created: {LIB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
