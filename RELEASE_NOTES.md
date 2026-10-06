# v1.0.17 —— 新增「统一管理器」开关；修复 Mod 快捷键被锁死、DLSS5 出帧判据空转

## 一、启动页新增「统一管理器」开关（默认开启）

* 位置：启动页开关列表**第一位**，**默认开启**。
* 作用：控制 **ReShade 底座与统一管理器面板**是否随游戏注入。开启时面板就位（游戏内按 `Home` 打开）；关闭时面板从 ReShade 目录移出。
* 与「Mod 快捷键锁定」**强绑定**：
  * 关闭「统一管理器」⇒「Mod 快捷键锁定」**强制关闭**；
  * 打开「Mod 快捷键锁定」⇒「统一管理器」**强制开启**。
* 该开关**不影响其它插件**：DLSS5 神经渲染、第一人称、汉化、喂帧、乳摇、Poser 各按各自开关。

## 二、修复：Mod 快捷键被锁死，而面板并未注入

* 症状：Mod 本身加载正常（`d3dx_user.ini` 中部件变量齐全、staging 里目录与 ini 俱在），但游戏内按 Mod 自带按键无反应，无法换装。
* 原因：`reshade_integration.takeover_possible()` 只检查"配置文件在不在磁盘上"，未检查"当前配置下 ReShade 底座是否真的会被注入"。当「DLSS5 神经渲染」与「第一人称视角」同时关闭时，注入库不再包含 `d3d12.dll`，游戏内没有 ReShade、面板不存在；而 Mod 的 `[Key*]` 仍被改写为 `VK_F24` ⇒ 原键与面板**两条路同时失效**。
* 修复：新增 `reshade_integration.reshade_base_wanted()` 作为**唯一判据**（锁键前与注入库共用同一份逻辑），底座不会注入时**拒绝改写热键**并在日志中说明理由。

## 三、修复：DLSS5 神经渲染「建立了特征却一帧未出」被误判为正常

* **判据读错文件**：原先读 `runtime\dlss5\ReShade.log`，而生效日志按 `RESHADE_BASE_PATH_OVERRIDE` 写在 `runtime\reshade\ReShade.log` ⇒ 该自检在正常配置下长期走"还没进过游戏，跳过"，等于空转。现已改读生效那份（读不到才回退旧路径）。
* **判据过松**：原先只要日志里出现 `evaluation succeeded` 即判"正常出帧"，而引擎**首帧**就会输出 `inline feature 18 evaluation succeeded (count=1, …)`。现在要求**帧号确实在增长**（`count>1`）。
* **新增自检项 `dlss5:nr_frames`**：命中 `NR workset pool exhausted`（引擎 workset 池 fail closed，每帧放行游戏自身画面）时明确报出"建立了特征、未产出帧"，并说明该状态**与设置无关** —— 改 NR 风格 / 强度 / 超分档位、重装组件、更换版本都不能改变它，避免继续消耗排查时间。

## 四、诊断包

* `ReShade.log` 关键行摘录**补收** `workset pool exhausted`、`NR workset completion fence could not be signaled`、D3D12 队列提交跟踪器安装失败三类行。
* 摘要新增 **「DLSS5 神经渲染出帧判据」** 段：给出"建特征 / 最大帧号 / 是否池耗尽 / 是否创建失败"的结论与现场原文。

## 五、修复：启动页开关点击后数秒才响应

* 原因有两处：
  * `set_hotkey_takeover` 在**同步路径**里执行 `prepare()`（重铺 staging、重新生成控制器与 `actions.tsv`，秒级）；
  * 前端在开关切换后 `await refreshState()`（整份状态）才更新界面。
* 现在：重活移交**后台线程**（接口立即返回）；开关值由接口回传的 `config` 立即回显，整份刷新不再阻塞界面。

## 六、测试

* 新增 `tests/test_minimal_injection.py`、`tests/test_hotkey_lock_guard.py`、`tests/test_nr_frames_judgement.py`，覆盖上述判据与联动。
* 反向验证：把各处修复逐条退回旧行为，对应测试 **5/5 全部变红**。

**附件**：`EndfieldModController.exe`、`assets-bundle.zip`（与上一版同名、不带版本号）。
