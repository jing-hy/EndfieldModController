# v1.0.24 —— 修复「NVIDIA 配置损坏」的清理只查了一个位置

## 一、修复：判据命中了，但清理空手而归

* **症状**：游戏启动后十几毫秒即自行退出，没有崩溃报告（退出码 `0xC0000135`），进程内存一路涨到 1 GB 以上。
* **上一版（v1.0.23）修好了"判据读哪份日志"**，这次日志里确实出现了命中提示，紧接着却是：

  ```
  Streamline 的 server manifest 读不懂，但没找到可清理的缓存文件（可能不在标准位置）
  ```

* **原因**：诊断采集列出了 **6 个** NVIDIA 配置根（`%LOCALAPPDATA%\NVIDIA\{Streamline,NGX}`、`%LOCALAPPDATA%\NVIDIA Corporation\NGX`、`%PROGRAMDATA%` 下三个），而**清理只查了其中一个** `%LOCALAPPDATA%\NVIDIA\NGX` ⇒ 目标文件在别的根里，于是"判据命中、动作没做"。
* **修复**：新增 `nvidia_config_roots()` 作为**唯一入口**，采集与清理共用同一份根列表（原则：**凡是"发现的路径"与"动手的路径"，只能有一处定义**）。

## 二、测试

* `tests/test_streamline_manifest.py` 增至 8 条，新增一条专门钉「**必须遍历全部已知根**」—— 把文件放在 `%PROGRAMDATA%` 那个根里，要求仍能被找到；另有一条钉住"内容正常的配置表不许动"；
* 反向验证：把清理退回"只查一个根"，对应测试变红；全量测试通过。

## 三、构建流程

* `build_release.py` 现在**构建完成后自动推送 main**（`--no-push` 可跳过）。这样多台机器之间始终能拉到与刚构建产物一致的源码。

**附件**：`EndfieldModController.exe`、`assets-bundle.zip`（与上一版同名、不带版本号）。
