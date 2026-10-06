# v1.0.16 —— DLSS5 神经渲染默认「启动即开」；修复一次启动拉起多个 XXMI

## 一、DLSS5 神经渲染默认「启动即开」

* 此前的默认策略是：启动前把 `[RenoDX.DLSS5] NeuralUplift` 压成 `0`，等第一人称插件打出 `Camera controls installed.` 之后再模拟一次 NR 快捷键补开。该策略依赖「第一人称启用时插件才会安装相机 hook」这一前提，因此**不使用第一人称的机器永远等不到那句话** ⇒ NR 始终不会被打开（面板「成功NR帧」长期停在个位数、`超分: 请求ON | 活动OFF`，实际画面来自游戏自身的 DLSS 输出）。
* 现在默认改为**启动即开**（写 `NeuralUplift=1`），不再依赖相机 hook：`CameraFirstPerson=1` 时二者共存已实测确认（相机 hook 先就位，`feature 18 created` 与 `evaluation succeeded` 紧随其后）；`CameraFirstPerson=0` 时不存在需要保护的相机 hook。
* 原「压 0 → 等待 hook → 模拟按键」路径**完整保留**：把新增开关 `start_dlss5_nr_immediately` 设为关闭即回到该策略。
* 自检项 `dlss5:nr_defer` 与 NR 自动开启模块的状态输出同步反映当前策略。

## 二、修复：一次「一键启动」拉起多个 XXMI Launcher

* 症状：单击一次一键启动后出现 4 个 `XXMI Launcher` 进程、各自加载一套 EFMI。日志显示启动流程入口被送达 4 次（间隔 68 毫秒 / 3.4 秒 / 2.7 秒），而**进程监视那一步是幂等的**（「进程监视已在运行，跳过重复启动」），唯独**真正拉起进程**这一步没有防护。
* 两道闸：
  * `launcher.launch()` 在拉起之前检查已有实例，已在运行则不再重复拉起；
  * `api.launch()` / `api.launch_game()` 使用**非阻塞**入口锁，重复请求直接返回 `duplicate`，不排队（排队会导致「点几次启动几次」）。
* 前端同步修正：「一键启动」的"正在启动"状态此前在若干次异步查询**之后**才置位，那段时间按钮仍可点击；现在提到任何 `await` 之前，并保证提前返回时复位。

## 三、修复：三处「看着在、实际未生效」的判据

* 注入现场时间线里的**签名长度恒为 0**：`dlss5_injection_status()` 的返回值中没有签名字段（而诊断包另一段直接读配置能得出 140），现已补齐 `extra_libraries_signature` / `user_signature`。
* 运行时采样里的 **ReShade 行数恒为 0**：采样读取的是 `runtime\dlss5\ReShade.log`（部署源目录），而生效日志按 `RESHADE_BASE_PATH_OVERRIDE` 写在 `runtime\reshade\`。
* 「**注入现场时间线**」段此前未接入 `summary.txt`（诊断包内有 `injection-trace.jsonl`、汇总里却没有对应段落），现已接入，并渲染五个时机、注入库逐条、以及「本该进入进程却没有进入的模块」。

## 四、诊断包采集范围扩充

* 新增 **Streamline / NGX 的清单与配置**（`%LOCALAPPDATA%` 与 `%PROGRAMDATA%` 下的 NVIDIA 目录，只收 ≤512 KB 的清单类文件，大缓存跳过）与**游戏目录下的小清单**（`*.json` / `*.ini` / `sl_*.txt`）。
* 新增 **`ReShade.log` 关键行摘录**（相机 hook / NR 建帧 / addon 注册 / hook 失败 / 报错），首轮排查不必再索取原始日志。
* 以上与既有采集共用同一入口，崩溃包与手动诊断包的输出保持一致。

## 五、内置组件

* `XXMI-Libs` 更新至 **v1.2.2**（上游 2026-10-05 发布）。装入点 `runtime\builtin\XXMI\Resources\Packages\XXMI`；升级前请先关闭 XXMI Launcher（它占用该目录会导致解压失败）。

## 六、测试

新增 `tests/test_injecttrace.py`、`tests/test_diagnosis_files.py`、`tests/test_diagnosis_wiring.py`、`tests/test_launch_dedup.py`，并按新默认更新 `tests/test_nr_autostart.py`。全量测试通过；反向验证 22 项**全部按预期失败**（即每处修复都被测试真正钉住）。

**附件**：`EndfieldModController.exe`、`assets-bundle.zip`（与上一版同名、不带版本号）。
