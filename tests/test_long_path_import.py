"""钉住「Windows 长路径（>260）也能导入」—— issue #12 的修复。

**issue 原文**：「mod无法解压」
```
解压失败：[Errno 2] No such file or directory: '...\\library\\庄方宜纹身肥美版（切换键 X ，ctrl+， 。？】 ；ctrl+5
方向键上下 8）fantasy_in_the_miragef_2\\庄方宜纹身肥美版（…）fantasy_in_the_miragef\\NoM_ZhuangFangyi_Fantasy in
the MirageF(MAX)V1.2\\Meshes\\Component0_IB.buf'
```
**实测根因**：那条路径 **264 字符** > Windows 上限 **259** ⇒
父目录建得出来、最后那个文件写不进去 ⇒ `[Errno 2]`。

**两条不变式**（本文件钉住）：
① 带**扩展长度前缀**（`\\\\?\\`）时，超长路径**能真的解开**（内容也对）；
② 退化成普通路径时**失败**，且给的是**可照做的中文指引**（含超长条目清单），
   **绝不能**把 `[Errno 2] No such file or directory` 这种英文 errno 甩给用户。
"""
from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest

from endfieldmodcontroller import api as A
from endfieldmodcontroller import longpath
from endfieldmodcontroller.config import AppConfig

LONG_NAME = "庄方宜纹身肥美版（切换键 X ，ctrl+， 。？】 ；ctrl+5 方向键上下 8）fantasy_in_the_miragef"
PAD = "x" * 40


def long_paths_enabled() -> bool:
    """本机是否**已开启** Windows 长路径支持（注册表 `LongPathsEnabled`）。

    为什么要问：不变式②的前提是"普通路径写不进 >260 的路径"。机器一旦开了长路径支持，
    去掉扩展前缀也照样写得进去 ⇒ 前提不成立、用例必然红（2026-10-10 在维护者这台机器上
    实测到）。这类"只对特定系统设置显形"的用例按条件跳过，而不是改判据去迁就。
    """
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\\CurrentControlSet\\Control\\FileSystem") as key:
            return int(winreg.QueryValueEx(key, "LongPathsEnabled")[0]) == 1
    except (OSError, ValueError, ImportError):
        return False


_skip_if_long_paths_on = pytest.mark.skipif(
    long_paths_enabled(),
    reason="本机已开启 Windows 长路径支持 —— 去掉扩展前缀后照样能写，不变式②的前提不成立",
)


def _api(tmp_path: Path) -> A.EndfieldModControllerApi:
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "library").mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = AppConfig.load(cfg_path)
    cfg.data_root = str(tmp_path)
    cfg.library_dir = "library"
    cfg.save()
    return A.EndfieldModControllerApi(str(cfg_path))


def _make_zip(cfg: AppConfig, root: Path) -> tuple[Path, Path, list[str]]:
    pkg = f"{LONG_NAME}_2.zip"
    dest = cfg.library_path / f"{LONG_NAME}_2"
    deep = f"{LONG_NAME}_2/NoM_ZhuangFangyi_Fantasy in the MirageF(MAX)V1.2/Meshes/{PAD}"
    members = [f"{deep}/Component0_IB.buf", f"{deep}/Component0_VB.buf"]
    path = root / pkg
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in members:
            zf.writestr(rel, b"Y" * 8192)
    return path, dest, members


def _import(api: A.EndfieldModControllerApi, path: Path) -> dict:
    begin = api.import_mod_begin(path.name)
    api.import_mod_chunk(begin["token"], base64.b64encode(path.read_bytes()).decode())
    return api.import_mod_finish(begin["token"])


def test_sample_is_actually_too_long(tmp_path: Path) -> None:
    """先确认这个测试样本**真的**超过 Windows 上限，否则整组测试没有意义。"""
    api = _api(tmp_path)
    _zip, dest, members = _make_zip(api.config, tmp_path)
    deepest = dest / members[0]
    assert longpath.is_too_long(deepest), (
        f"样本不够长（{longpath.path_length(deepest)}），这组测试测不到东西")
    assert longpath.path_length(deepest) > longpath.MAX_PATH_CHARS


def test_long_path_zip_extracts(tmp_path: Path) -> None:
    """★ 超长路径的 zip 能真的解开，内容也对。"""
    api = _api(tmp_path)
    zip_path, _dest, _members = _make_zip(api.config, tmp_path)
    result = _import(api, zip_path)
    assert result.get("ok"), f"应当成功，实际：{str(result.get('message'))[:400]}"
    # ⚠️ **不能用 `rglob` 找**（2026-10-03 实测）：`Path.rglob` / `iterdir` 自己**也受
    # 260 限制**，在超长目录下会**静默返回空** —— 拿它当判据会得出"没解出来"的错误结论。
    # 所以这里用 `os.walk` + 扩展长度前缀来数。
    import os

    dest = str(result["dest"])
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(longpath.extended(dest)):
        for name in filenames:
            if name.endswith(".buf"):
                found.append(os.path.join(dirpath, name))
    assert len(found) == 2, f"应当解出 2 个 .buf，实际 {len(found)}（{found}）"
    assert all(os.path.getsize(p) == 8192 for p in found), "解出来的内容长度不对"


@_skip_if_long_paths_on
def test_falls_back_to_readable_chinese(tmp_path: Path, monkeypatch) -> None:
    """★ 没有长路径支持时**失败**，但给的是可照做的中文指引（不是英文 errno）。"""
    api = _api(tmp_path)
    zip_path, _dest, _members = _make_zip(api.config, tmp_path)
    monkeypatch.setattr(longpath, "extended", lambda p: str(p))     # 关掉前缀
    result = _import(api, zip_path)
    assert result.get("ok") is False, "关掉长路径支持后应当失败"
    assert result.get("long_path") is True, "应当带上 long_path 标记"
    message = str(result.get("message") or "")
    assert "超过 Windows 的长度上限" in message, f"缺少人话说明：{message[:200]}"
    assert "怎么办" in message, "应当告诉用户怎么办"
    # 不能把英文 errno 当结论甩给用户（说明里解释成因时可以提，但结论必须是中文）
    assert not message.startswith("解压失败：[Errno"), "不该以英文 errno 开头"


def test_longpath_helpers(tmp_path: Path) -> None:
    """`extended()` / `path_length()` / `is_too_long()` 的基本行为。"""
    import os

    if os.name != "nt":
        pytest.skip("仅在 Windows 上有意义")
    p = tmp_path / "a" / "b"
    ext = longpath.extended(p)
    assert ext.startswith("\\\\?\\"), ext
    # 已经带前缀的不重复加
    assert longpath.extended(ext) == ext
    # 长度按"去前缀"算
    assert longpath.path_length(ext) == len(str(p).replace("/", "\\"))
    assert not longpath.is_too_long(p)
    assert longpath.is_too_long("D:\\" + "a" * 300)
