"""版本号与仓库信息（窗口标题、右上角更新检测、自我更新共用一处）。

改版本号只需要改这里 + 打对应 tag（如 `v0.2.7`）的 GitHub release。

版本号规则（用户 2026-09-27 定）：**与 GitHub 上的有区别就升下一版，但没推送时只领先一个** ——
即 GitHub 最新是 v0.2.6 时，本地不管累积多少改动都保持 0.2.7，推送发版后才继续往上走。
"""
from __future__ import annotations

APP_NAME = "EndfieldModController"
__version__ = "0.2.7"

# 自我更新与"检查更新"指向的仓库
REPO = "jing-hy/EndfieldModController"
REPO_URL = f"https://github.com/{REPO}"
RELEASES_URL = f"{REPO_URL}/releases"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"{APP_NAME}/{__version__}"

# 窗口/界面标题
WINDOW_TITLE = f"{APP_NAME} v{__version__}"
