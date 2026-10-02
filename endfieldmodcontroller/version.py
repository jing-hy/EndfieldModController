"""版本号与仓库信息（窗口标题、右上角更新检测、自我更新共用一处）。

改版本号只需要改这里 + 打对应 tag（如 `v0.4.0`）的 GitHub release。

版本号规则（用户 2026-09-27 定，**2026-10-02 澄清**）：
**版本号只跟"最新 Release"比 —— 本地保持在「最新 Release + 1」；
GitHub 上只推了源码（main 更新）但没发 Release 时，版本号不用改。**

即：最新 Release 是 v0.9.3 时，本地不管累积多少改动、main 上又推了多少次源码，都保持 0.9.4；
**只有发过 Release 之后**才轮到 0.9.5。可执行的核对见 `scripts/release_version.py`
（`build_release.py` / `prepare_release.py` 各跑一遍，改号前后都能看到结论）。
"""
from __future__ import annotations

APP_NAME = "EndfieldModController"
__version__ = "0.9.4"

# 自我更新与"检查更新"指向的仓库
REPO = "jing-hy/EndfieldModController"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"{APP_NAME}/{__version__}"

# 窗口/界面标题
WINDOW_TITLE = f"{APP_NAME} v{__version__}"
