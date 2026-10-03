"""RabbitFX 随包分发与展开（2026-10-03 用户要求：「**那把他随包**」）。

**RabbitFX 是什么**（作者 caverabbit，GameBanana 651557，CC BY-NC-ND 4.0）：
终末地 Mod 的**共享 shader 特效前置** —— 用 `[ShaderRegex*]` 正则改写角色 shader，
往里插额外贴图槽（`t60/t61` Glow、`t70–t74` Diffuse/Lightmap/Normal/Discard/Rain），
并做去马赛克与 HSV 调色。庄方宜的模块化菜单包（`snaccubus-…-modularmenumod`）等
Mod 明确要求它（它的 `README.txt` 第一行就写着 `Requires RabbitFX library`）。

**为什么要随包**：它本体只有 **6 KB**（上游 `v26_b2546.zip` = 6,160 B），
而从 GameBanana 拉取在国内线路上可能只有 8 KB/s（实测），为这 6 KB 让用户等/失败不值得。
随包放在 `assets/rabbitfx/`，启动自检时展开。

**装到哪**：`<Mod 库>/_deps/RabbitFX` —— **与 `dependencies.json` 里声明依赖时的安装位置
一致**，这样"随包展开"和"按依赖下载"两条路落到同一个地方，不会各铺一份。

⚠️ **作者的硬性警告**：`Having multiple RabbitFXs will cause unexpected behaviours and
game crashes … only ever have one instance of RabbitFX anywhere in your mods folder`。
所以 `ensure_bundled()` 在目标已存在时**什么都不做**，并且会在库里发现第二份时报出来。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

Log = Callable[[str], None] | None

# 展开目标（相对 Mod 库）—— 与 dependencies.json 的 install_dir 保持一致
INSTALL_REL = Path("_deps") / "RabbitFX"
# 判定"已装好"的必需文件
REQUIRED_FILE = "RabbitFX.ini"
# 随包目录名
ASSET_GROUP = "rabbitfx"


def _log(log: Log, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def assets_root(config: AppConfig | None = None) -> Path:
    """随包资产根目录。

    `assets` 位于**数据根**（exe 所在目录），与 `config.json` / `runtime` / `library` 同级。
    这才是"从 Release 下载 exe + assets-bundle.zip"解出来的形态；`__file__` 在打包后指向
    PyInstaller 的临时解压目录，那里没有 assets（见 `secondary_motion._assets_root` 的说明）。
    """
    if config is not None:
        base = getattr(config, "base_dir", None) or getattr(config, "data_root", None)
        if base:
            return Path(base) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def bundled_source(config: AppConfig) -> Path | None:
    """随包里那份 RabbitFX 的目录（不存在返回 None）。"""
    candidate = assets_root(config) / ASSET_GROUP
    if (candidate / REQUIRED_FILE).is_file():
        return candidate
    return None


def install_dir(config: AppConfig) -> Path:
    """展开目标：`<Mod 库>/_deps/RabbitFX`。"""
    return Path(config.library_path) / INSTALL_REL


def is_installed(config: AppConfig) -> bool:
    return (install_dir(config) / REQUIRED_FILE).is_file()


def find_duplicates(config: AppConfig) -> list[Path]:
    """在 Mod 库里找**除了目标之外**的 RabbitFX（作者警告多份会崩）。

    只扫库的第一层与 `_deps` 一层，够用且便宜；命中就交给调用方如实报出来。
    """
    out: list[Path] = []
    target = install_dir(config).resolve() if is_installed(config) else None
    try:
        roots = [Path(config.library_path), Path(config.library_path) / "_deps"]
    except (OSError, AttributeError):
        return out
    for root in roots:
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if not (child / REQUIRED_FILE).is_file():
                    continue
                # 目标是正常的，不算重复
                try:
                    if target is not None and child.resolve() == target:
                        continue
                except OSError:
                    pass
                # `(重要前置)RabbitFX v24_3d366` 这类用户自己放的不算"重复安装"，
                # 但确实会被 EFMI 一起加载 —— 如实报出来让用户决定。
                out.append(child)
        except OSError:
            continue
    return out


def ensure_bundled(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """把随包的 RabbitFX 展开到 `<Mod 库>/_deps/RabbitFX`（幂等）。

    * **目标已存在** ⇒ 什么都不做（**绝不覆盖**：用户可能自己更新过它）；
    * 库里**已有别的 RabbitFX** ⇒ 不铺，如实报告（作者警告多份会崩）；
    * 随包里没有 ⇒ 返回 `missing`，由依赖下载那条路兜底。
    """
    if is_installed(config):
        dup = find_duplicates(config)
        if dup:
            _log(log, "RabbitFX 已就位；但库里还有其它副本（作者警告多份会崩）："
                      + "、".join(p.name for p in dup))
        return {"ok": True, "status": "present", "dir": str(install_dir(config))}

    dup = find_duplicates(config)
    if dup:
        _log(log, "库里已有一份 RabbitFX（" + "、".join(p.name for p in dup)
                  + "），不再重复铺随包那份（作者警告多份会导致异常与崩溃）")
        return {"ok": True, "status": "already_elsewhere", "dir": str(dup[0])}

    src = bundled_source(config)
    if src is None:
        return {"ok": False, "status": "missing",
                "message": "随包 assets\\rabbitfx 不存在（重新展开一次 assets-bundle.zip 即可）"}

    target = install_dir(config)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 先拷到临时目录再改名：中断也不会留下半份
        tmp = target.with_name(target.name + ".mc-tmp")
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp)
        # 随包的 manifest.json 是给我们自己看的，不进 Mod 目录
        (tmp / "manifest.json").unlink(missing_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
    except OSError as exc:
        return {"ok": False, "status": "error", "message": f"展开失败：{exc}"}

    _log(log, f"RabbitFX：随包展开到 {target}")
    return {"ok": True, "status": "installed", "dir": str(target)}
