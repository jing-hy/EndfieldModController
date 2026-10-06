# v1.0.22 —— 修复「自检无缺失却打不开」：注入库列到了错的 EFMI loader

## 一、修复：写注入库之前先把 EFMI 的 loader 部署到位

* **症状**：启动时弹出「**注入额外库 `…\Resources\Packages\XXMI\d3d11.dll` 失败：DLL 注入失败！**」，**整个启动中断**；而自检报告**一切正常**（时好时坏）。
* **机理**（两次运行对照定位）：XXMI 的 `extra_libraries` **必须**列出 EFMI 的 `d3d11.dll` —— 不列的话 XXMI 会把自带那份补到列表**最前面**，变成"EFMI 先、ReShade 后"，游戏起不来；**但只能列 XXMI 自己实际会用的那一份**。若列的是**包目录**里的副本，XXMI **去重不掉**，注入请求会变成 `Inject('d3d11.dll, d3d12.dll, d3d11.dll')` ⇒ **第二次注入必然失败并中断启动**。
* **为什么时好时坏**：在"刚拉起 XXMI 生成配置、EFMI 还没部署"的那一刻，`EFMI\d3d11.dll` 尚不存在，取 loader 的逻辑会回退到**包目录那份**，于是写进注入库的就是另一条路径；而 XXMI 随后会自己把那份部署到 `EFMI\d3d11.dll` 并注入它 ⇒ 同一份 DLL、两个路径。
* **修复**：写入注入库**之前**，先把包目录里的 `d3d11.dll` 部署到 `EFMI\d3d11.dll`（XXMI 自己稍后也会做，这里只是提前一步）⇒ 回退分支不会再被走到，`extra_libraries` 里永远是"XXMI 实际会用的那一份"。

## 二、修复：NR 与第一人称相机 hook 抢位（按「要不要用第一人称」分流）

* **症状**：第一人称与相机控制都用不了；日志里 `Endfield enhancer: Camera hook installation failed; camera controls disabled.`（`error 8`）。
* **机理**：enhancer 的**相机 hook** 与 NR 抢同一个位置 —— **NR 先激活 ⇒ hook 装不上**。而自 v1.0.16 起默认「NR 启动就开」（`NeuralUplift=1`）⇒ 必然抢先。
* **修复**：按"这台机器用不用第一人称"分流 ——
  * `[endfield-enhancer] CameraFirstPerson=1` ⇒ 启动前把 `NeuralUplift` 压成 **0**，等 `Camera controls installed.` 出现后由自动逻辑补按一次 NR 快捷键 ⇒ **相机 hook 与 NR 都在**；
  * `CameraFirstPerson=0` ⇒ 保持「启动就开」⇒ 没有 hook 要保护，NR 照样自动出帧。
* 判据读的是**生效那份** `ReShade.ini`（只在 `[endfield-enhancer]` 段内取值）；读不到时按"不用第一人称"处理。

## 三、新增：NVIDIA Streamline / NGX 的 server manifest 损坏判据与自动修复

* **现场**：游戏启动后 **15 毫秒**连打 10 条 `[streamline][error] ota.cpp:329 [parseServerManifest] Unexpected line in manifest file`，随后**内存从 627 MB 涨到 1694 MB**、线程掉到 1、进程**自己退出** —— **没有 WER、面板 add-on 也正常卸载**，因此"崩溃取证"一条都抓不到。
* **新增判据**：读游戏 `Player.log`，命中上述特征即报出「Streamline 的 server manifest 读不懂」。
* **自动修复**：把 NGX 的 server manifest 与 Streamline 的 OTA 缓存**备份移走**（移到 `.mc-backup-<时间戳>`，**只搬不删、可还原**；只取名字含 `manifest`/`server`/`ota`/`cache` 的文件），驱动下次启动会自己重建。

## 四、测试

* 新增 `tests/test_efmi_loader_deploy.py`（4 条）、`tests/test_nr_firstperson_split.py`（5 条）、`tests/test_streamline_manifest.py`（4 条）等；
* 反向验证：把各处修复逐条退回旧行为，对应测试全部变红；全量测试通过。

**附件**：`EndfieldModController.exe`、`assets-bundle.zip`（与上一版同名、不带版本号）。
