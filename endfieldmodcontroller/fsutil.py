"""Small filesystem helpers shared by the whole controller.

2026-10-01：把两件被重复实现了 N 遍的东西收成一份 ——

* `sha256_file`：项目里曾有 6 份各自实现（dependencies / fastnet / game_clean /
  runtime_assets / selfupdate / pack_nvngx）外加两处内联。重复的代价很实在：
  "想给下载统一加校验"时改不全，就会出现**能力存在但没人用**的局面。
* `write_*_atomic`：直接 `write_text` 覆盖写，写到一半被杀/断电就留下半截文件
  （配置、controller 产物、marker 都踩过），统一走"临时文件 + os.replace"。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable


#: 终末地日志目录下的**厂商段**：国服是 `Hypergryph`，国际服与其它渠道是 `Gryphline`。
ENDFIELD_VENDORS = ("Hypergryph", "Gryphline")


def endfield_local_low_dirs() -> list[Path]:
    """游戏自己的 LocalLow 目录候选（`...\\LocalLow\\<厂商>\\Endfield`），**存在的排前面**。

    ⚠️⚠️ **两家厂商都要认**（2026-10-07 从两个反馈者的诊断包做对照时查出）：
    国服是 `Hypergryph`、国际服与其它渠道是 `Gryphline`（他们的游戏目录叫
    `Arknights Endfield`）。项目里曾**有四处把厂商写死成 `Hypergryph`**，于是国际服用户
    那边这些判据**全部静默失效** —— 实测后果：`crashwatch.streamline_manifest_broken()`
    读不到 `Player.log` ⇒ "检测到 Streamline 的 server manifest 报错就自动换新版运行库"
    这条**一次都没触发过**（issue #16 换上 v1.1.1 之后，包里仍然是 10 条
    `parseServerManifest` 报错，本该被自动换掉的新版一直没装）。

    **两个都返回**（存在的排前面）：调用方要能区分"读不到"和"没去看"。
    """
    base = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow"
    dirs = [base / vendor / "Endfield" for vendor in ENDFIELD_VENDORS]
    return sorted(dirs, key=lambda path: (not path.is_dir(), str(path)))


def sha256_file(path: Path, progress: Callable[[int, int], None] | None = None) -> str:
    """分块计算文件 sha256；`progress(done, total)` 可选（用于界面进度）。"""
    path = Path(path)
    digest = hashlib.sha256()
    try:
        total = path.stat().st_size
    except OSError:
        total = 0
    done = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return digest.hexdigest()


def norm_sha256(value: str) -> str:
    """把 ``sha256:xxxx`` / 大小写混杂的期望值规范成纯小写十六进制。

    前缀匹配**不区分大小写**：GitHub 目前给的是小写 `sha256:`，但别的来源
    （自建清单、手工填写）随时可能写成 `SHA256:` 或带空格。
    """
    text = str(value or "").strip()
    if text.lower().startswith("sha256:"):
        text = text[7:]
    return text.strip().lower()


def unique_sibling(path: Path) -> Path:
    """返回一个**不会覆盖已有文件**的相邻名字（备份只增不删）。"""
    path = Path(path)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.name}-{os.getpid()}")


def _tmp_path(path: Path, attempt: int = 0) -> Path:
    """临时文件名：带 pid 与 attempt，**每次重试换一个**（见 `_atomic_write`）。"""
    return path.with_name(f"{path.name}.mc-tmp-{os.getpid()}-{attempt}")


def _atomic_write(
    path: Path,
    data: bytes | str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    backup: bool = False,
    attempts: int = 6,
) -> Path:
    """原子写的唯一实现（临时文件 + `os.replace`），**带退避重试与每次换名**。

    为什么要重试、要换名（2026-10-04 从 `config.save` 下沉到这里）：
    * 用户实测过 `[WinError 2] 系统找不到指定的文件: 'config.json.tmp-10116' -> 'config.json'`
      —— `write_text` 明明成功，轮到 `os.replace` 时临时文件已经没了，这是**杀软实时扫描**
      把刚写出的文件吃掉的特征（他机器上就有）。扫描只持续几十~几百毫秒，退避重试即可。
    * 每次换一个临时名：被杀软"记住"的那个名字重试也大概率再被吃掉。
    * 名字里带 **`attempt` 序号**顺带解决另一个竞态：原实现临时名只带 pid，
      **同一进程内两个线程写同一个文件会共用同一个临时文件**（交错写 → 内容损坏）。
    * `WinError 5 拒绝访问` 通常是另一个实例正在 replace 同一个文件，占用更久，
      所以退避随时间线性加长。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        shutil.copy2(path, unique_sibling(path.with_name(path.name + ".bak")))
    last_exc: OSError | None = None
    for attempt in range(attempts):
        tmp = _tmp_path(path, attempt)
        try:
            if isinstance(data, bytes):
                tmp.write_bytes(data)
            else:
                tmp.write_text(data, encoding=encoding, newline=newline)
            os.replace(tmp, path)
            return path
        except OSError as exc:
            last_exc = exc
            try:
                tmp.unlink()
            except OSError:
                pass
            time.sleep(0.15 * (attempt + 1))       # 150/300/450/600/750/900ms
    if last_exc is not None:
        raise last_exc
    return path


def write_bytes_atomic(path: Path, data: bytes, *, backup: bool = False) -> Path:
    """原子写入字节；`backup=True` 时先留一份不覆盖的 .bak。"""
    return _atomic_write(Path(path), data, backup=backup)


def write_text_atomic(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    backup: bool = False,
) -> Path:
    """原子写入文本（同 `write_bytes_atomic`）。"""
    return _atomic_write(Path(path), text, encoding=encoding, newline=newline, backup=backup)


# ---------------------------------------------------------------------------
# 「不要动用户的 Mod 库」护栏（用户 2026-10-01 定的硬规则）
# ---------------------------------------------------------------------------
def library_conflict(library_root: Path | None, target: Path | None) -> str:
    """目标路径与 Mod 库的关系：``""`` = 安全；否则返回**危险原因**。

    用户原话：「**任何情况（除用户手动点击移出库外）都不要动用户的 mod 库（包括换位置）**」。
    危险有三种，任何一种都不许删/移：

    * 目标**就是**库本身（`library\\`）；
    * 目标**在库里面**（`library\\某个 Mod`）—— 删它就是删用户的 Mod；
    * 目标是库的**上级目录**（例如把 `runtime\\` 或数据根当成 staging 去清空）—— 会连库一起端掉。

    为什么要有它：清理 staging、收编手动 Mod、安装/重装组件这些流程都会 `rmtree`，
    而一旦用户的 `library_dir` 与 `staging_mods_dir` 相同或互相嵌套（老教程让人把 Mod
    放进 `EFMI\\Mods`，很容易配成这样），清理 staging 就等于**把库删光**
    （2026-10-01 一条外部反馈：「重装的时候还把我 mod 都删完了，还好我备份了」）。
    """
    if library_root is None or target is None:
        return ""
    try:
        lib = Path(library_root).resolve()
        tgt = Path(target).resolve()
    except OSError:
        return ""
    if lib == tgt:
        return f"目标就是 Mod 库本身（{lib}）"
    if lib in tgt.parents:
        return f"目标在 Mod 库内（{tgt}）"
    if tgt in lib.parents:
        return f"目标是 Mod 库的上级目录（{tgt} 包含了 {lib}）"
    return ""


def is_library_safe(library_root: Path | None, target: Path | None) -> bool:
    """``library_conflict(...) == ""`` 的可读写法。"""
    return not library_conflict(library_root, target)


# ---------------------------------------------------------------------------
# 路径包含判定（**别再用字符串前缀**）
# ---------------------------------------------------------------------------
def is_within(root: Path | None, target: Path | None) -> bool:
    """`target` 是否**就在** `root` 里面（含相等）。取不到真实路径时返回 False（保守）。

    ⚠️ 为什么不写 `str(target).startswith(str(root))`（项目里曾有四份这种写法）：
    `C:\\lib\\foo` 是 `C:\\lib\\foobar` 的字符串前缀，于是 `foobar` 会被误判成
    "在 foo 里"；反过来 `C:\\lib\\foo\\..\\bar` 又"看起来还在 foo 里"。
    两种情况都真实踩过（一次是下载入库后找不到刚导入的 Mod，一次是解压的
    zip-slip 校验被绕过）。统一走 `resolve()` + `is_relative_to()`。
    """
    if root is None or target is None:
        return False
    try:
        return Path(target).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def safe_join(root: Path, relative: str | Path) -> Path | None:
    r"""把**外部给的相对路径**（压缩包成员名 / 远端文件名）安全地拼到 `root` 下。

    不安全就返回 ``None``，由调用方拒绝这一条：
      * 绝对路径、UNC、带盘符（`C:\Windows\x`、`\\\\server\\share`、`/etc/passwd`）；
      * 任何一段是 `..`（`..\..\x` 会逃出 root —— 而字符串前缀判断**看不出来**，
        因为 `root\..\x` 的字符串确实以 `root` 开头）；
      * 空名字。

    为什么单独抽出来：解压是"外部数据直接落盘"的入口。项目里 `_extract_zip_into_long`
    曾用字符串前缀做 zip-slip 校验，`..\foobar\x.ini` 能同时骗过前缀判断与
    `dest / member` 的拼接语义 —— 包里的文件会写到 Mod 库**外面**。
    """
    text = str(relative or "").replace("\\", "/").strip()
    if not text:
        return None
    if text.startswith("/") or text.startswith("//"):
        return None
    if len(text) > 1 and text[1] == ":":
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    target = Path(root)
    for part in parts:
        target = target / part
    return target


# ---------------------------------------------------------------------------
# 文本读取（编码容错）—— 原先在 core.read_text 与 config 的配置读取处各写一份
# ---------------------------------------------------------------------------
# 编码尝试顺序：**GBK 必须排在 cp932 前面**。
# 理由（2026-10-04 用真实字节实测出来的）：GBK 的"暗色"（B0 B5 C9 AB）在 cp932 眼里
# 是一串**能解码但不正确**的半角片假名（`ｰｵﾉｫ`）—— 也就是说"能解码"不等于"解对了"。
# 两边都会互相误判，所以只能按**本项目的用户分布**取舍：这是一个中文 Windows 用户为主的
# 工具，用户拿记事本「另存为 ANSI」（=GBK）改 config.json / 中文 Mod 名是最常见的情况；
# `utf-8` 依然排在它们前面（我们自己写出去的文件就是 UTF-8）。
_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "cp932", "latin-1")


def read_text_tolerant(path: Path) -> str:
    """读文本，**容忍 BOM 与旧编码**（utf-8-sig / utf-8 / cp932 / gbk / latin-1）。

    为什么必须有：Windows 用户用记事本「另存为 ANSI」改配置文件是极常见的操作，
    而 `path.read_text(encoding="utf-8")` 在这种情况下抛的是 **`UnicodeDecodeError`**
    —— 它**不是** `OSError`、也不是 `JSONDecodeError`，于是调用方那条
    「坏了就隔离并重建」的自愈分支**完全走不到**，异常直接冒出去：
    `config.json` 一旦是 GBK，程序连窗口都起不来（2026-10-04 审计发现）。

    文件不存在/无权限仍照旧抛 `OSError`，由调用方决定（这是"读不到"不是"读坏了"）。
    """
    raw = Path(path).read_bytes()
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# JSON 状态文件读写（曾经在 alerts / character_sync / sbm_data_sync 各写一份）
# ---------------------------------------------------------------------------
def read_json(path: Path) -> dict[str, Any]:
    """读一个 JSON 对象；**读不到 / 坏了 / 不是对象**一律返回 ``{}``（绝不抛）。

    状态文件（公告缓存、角色表、节流记录）坏了只该导致"这次当没有"，
    不该让调用方崩掉 —— 这是三处各自实现时共同的语义，收成一份。
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def loads_tolerant(text: str) -> Any:
    """解析"可能带前置杂质"的 JSON 文本（网络响应常见）。

    **为什么要它（2026-10-06 本机实测复现）**：香蕉网
    `https://gamebanana.com/apiv11/Mod/<id>/ProfilePage` 会在 JSON **前面**打出一条
    PHP Warning ——

        Warning: Undefined array key "oneclick_support" in .../TableRowCacher.php on line 87
        { "_idRow": 690864, … }

    直接 `json.loads(整段)` 会报 `Expecting value: line 2 column 1 (char 1)`，
    用户看到的是「Mod 下载失败：返回的不是有效数据」，而它**与网络、代理、VPN 全无关系**
    （带/不带代理、带/不带浏览器 UA，服务端返回逐字节一样）。

    做法：先按正常 JSON 解析；失败则从第一个 `{` / `[` 起用 `raw_decode` 逐个候选位置重试
    —— 只认**真能解析出 JSON** 的位置，不做"掐头去尾"的猜测。
    """
    try:
        return json.loads(text)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _end = decoder.raw_decode(text, index)
        except ValueError:
            continue
        return value
    raise ValueError("响应里没有可解析的 JSON")


def write_json(path: Path, payload: Any) -> None:
    """原子写 JSON（临时文件 + ``os.replace``）；失败**抛 OSError**，由调用方决定。

    与 `write_text_atomic` 同一套原子语义，只是统一了 `ensure_ascii=False / indent=2`
    这两个"给人看的状态文件"约定（原来三处各写一遍，格式已经漂了）。
    """
    write_text_atomic(
        Path(path),
        json.dumps(payload, ensure_ascii=False, indent=2),
        newline="\n",
    )


# ---------------------------------------------------------------------------
# 下载缓存目录（dependencies / updates 曾各写一份逐字节相同的实现）
# ---------------------------------------------------------------------------
def downloads_cache_dir() -> Path:
    """组件安装包的下载缓存目录（``<数据根>/runtime/_downloads``）。

    读不到配置时退回 ``<cwd>/runtime/_downloads``（与两份旧实现一致）。
    """
    from .config import AppConfig

    try:
        return AppConfig.load().runtime_path / "_downloads"
    except Exception:  # noqa: BLE001
        return Path.cwd() / "runtime" / "_downloads"
