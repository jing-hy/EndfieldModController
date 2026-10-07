"""版本号与仓库信息（窗口标题、右上角更新检测、自我更新共用一处）。

改版本号只需要改这里 + 打对应 tag（如 `v0.4.0`）的 GitHub release。

版本号规则（用户 2026-09-27 定，2026-10-02 澄清，**2026-10-04 加 beta 约定**）：
**版本号只跟"最新 Release"比 —— 本地保持在「最新 Release + 1」；
GitHub 上只推了源码（main 更新）但没发 Release 时，版本号不用改。**

**2026-10-04 用户新增（原话）**：「在正式推版本之前，都采用比 release 多一，但是加 -beta，
检测到 github 正式版要跳更新，比如 1.0.9 比 1.0.9-beta 新」+「推 release 的都不带 beta」。落地：
  * **未发版**：本地版本 = 「最新 Release + 1」+ **`-beta`**（Release 是 `1.0.9` ⇒ 本地 `1.0.10-beta`）；
  * **同号时正式版更新**：`1.0.9` **比** `1.0.9-beta` 新（beta 是预发布语义，与 PEP 440 一致）
    ⇒ 用户手上装着 `1.0.9-beta` 时，一旦 `1.0.9` 正式发布，更新检测**必须**提示可更新；
  * **发 Release 时去掉 beta**：tag 与正文都是 `1.0.10`（`strip_prerelease` 负责这一步）。

`1.0.9` 与 `1.0.10-beta` 谁新？**后者**（数字大）；`1.0.9` 与 `1.0.9-beta` 谁新？**前者**。
两种情形都由 `parse_version` 一套口径回答，别再各处自己用正则抠数字 —— 全项目
一共出现过 5 份同款实现（`updates` / `selfupdate` / `github` / `alerts` / `dlss5_fetcher`），
加一维语义时漏掉任何一处都会变成"更新检测时灵时不灵"。
"""
from __future__ import annotations

import re

APP_NAME = "EndfieldModController"
__version__ = "1.2.1"

# 自我更新与"检查更新"指向的仓库
REPO = "jing-hy/EndfieldModController"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"{APP_NAME}/{__version__}"

# 窗口/界面标题
WINDOW_TITLE = f"{APP_NAME} v{__version__}"

# 预发布后缀（`-beta` / `-rc.1` / `+build` 都算预发布）
_PRERELEASE = re.compile(r"[-+]")


def strip_prerelease(value: str) -> str:
    """去掉 `-beta` 之类的预发布后缀 —— **发 Release 时用**。

    用户 2026-10-04：「推 release 的都不带 beta」。所以 tag、Release 标题、正文里的版本号
    一律走这里，保证"本地 `1.0.10-beta` ⇒ 线上 `v1.0.10`"。
    """
    text = str(value or "").strip().lstrip("vV")
    return _PRERELEASE.split(text)[0].strip() or "0"


def parse_version(value: str) -> tuple[int, ...]:
    """把版本串解析成**可比较的元组**，把"是不是预发布"编码进最后一维。

    比较键 = `(数字…, 1 或 0)`，**正式版 1 / 预发布 0**：
      * `1.0.10-beta` → `(1, 0, 10, 0)`
      * `1.0.10`      → `(1, 0, 10, 1)`
      * `1.0.9`       → `(1, 0, 9, 1)`
    ⇒ `1.0.10-beta > 1.0.9`（数字大）且 `1.0.9 > 1.0.9-beta`（同号时正式版更新），
      两条正是用户要的语义。
    """
    text = str(value or "").strip().lstrip("vV")
    prerelease = bool(_PRERELEASE.search(text))
    numbers = tuple(int(part) for part in re.findall(r"\d+", _PRERELEASE.split(text)[0]))
    if not numbers:
        # ⚠️ **一个数字都取不出来时保持旧口径 `(0,)`**（不加"预发布"那一维）：
        #    `alerts.version_applies` 等地方就是靠"取不出数字"来判"未知版本 ⇒ 不挡"，
        #    返回 `(0, 0)` 会让那个判据失效（2026-10-04 实测：1 个既有测试因此变红）。
        return (0,)
    return numbers + ((0,) if prerelease else (1,))


def is_newer(candidate: str, current: str) -> bool:
    """`candidate` 是否比 `current` 新（更新检测与自我更新的唯一判据）。"""
    return parse_version(candidate) > parse_version(current)


def same_release(a: str, b: str) -> bool:
    """忽略预发布后缀后是不是同一个版本号（`1.0.10-beta` 与 `1.0.10` ⇒ True）。"""
    return parse_version(strip_prerelease(a))[:3] == parse_version(strip_prerelease(b))[:3]
