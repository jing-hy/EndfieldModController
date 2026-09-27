"""版本号与仓库信息（窗口标题、右上角更新检测、自我更新共用一处）。

改版本号只需要改这里 + 打对应 tag（如 `v0.2.2`）的 GitHub release。
"""
from __future__ import annotations

APP_NAME = "EndfieldModController"
__version__ = "0.2.2"

# 自我更新与"检查更新"指向的仓库
REPO = "jing-hy/EndfieldModController"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"{APP_NAME}/{__version__}"

# 窗口/界面标题
WINDOW_TITLE = f"{APP_NAME} v{__version__}"
