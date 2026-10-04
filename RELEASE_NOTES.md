# v1.0.10 —— 注入顺序、面板自证、诊断一次抓全、热重载

本版来自两份用户诊断包与两张截图（ReShade 插件加载失败码 `4551`、XXMI 弹「EFMI 加载失败：注入额外库 … DLL 注入失败！」、游戏内 CRT 的 Runtime Error 框）。**都不是 GitHub issue 报来的**，所以正文里按来源写明现场。

## 一、EFMI 的 `d3d11.dll`：注入顺序修对了

`extra_libraries` 里那条 EFMI loader 经历了三次结论，现在定案 —— **必须列、必须排在 ReShade 底座之后、而且只能列"当前生效那个 XXMI 自己那份"**：

* **不列**：XXMI 会把自带那份补到注入列表**最前面**，变成「EFMI 先、ReShade 后」⇒ **游戏起不来**（实测：能玩 122 秒 → 25 秒退出）；
* **列错的那份**（用外部 XXMI 时列了内置那份）：XXMI 按路径去重不掉 ⇒ `Inject('d3d11.dll, d3d12.dll, d3d11.dll')` ⇒ 第二次注入必然失败 ⇒ **弹窗中断启动**；
* 现在这条路径由 XXMI 配置的 `Importers.EFMI.Importer.importer_folder` 解析（相对路径相对 XXMI 根），**外部 XXMI 与内置 XXMI 都能得到正确结果**。

## 二、面板 addon（`endfieldmodcontroller.addon64`）

* **DllMain 只留"注册 + 一行裸 Win32 自证日志"**，读清单 / 装 EFMI 读键 hook / 读界面设置全部挪到首帧（渲染线程）并整体包异常 —— 原来这些都挤在 loader lock 下；
* **加载失败会写明原因**：`register_addon FAILED (api=… last_error=…)`；若连 `DllMain attach: begin` 都没有，说明是 LoadLibrary 阶段被外部拦下（安全软件/文件问题），不是内部失败；
* 两份编译脚本参数对齐（`/MT /O2 /utf-8 /Brepro`），不再出现"同源码两种产物"。

## 三、诊断包：一次抓全

新增/修正这些判据（以前要么没采、要么采了没人解析）：

* **ReShade 插件加载结果**：谁 `Registered add-on`、谁 `Failed to load … with error code`、谁的**同名重复**被拒、扫描目录是哪个；
* **面板自己的日志**（`modecontroller.addon.log`）—— 以前找的文件名是错的（`endfieldmodcontroller.addon.log`），**每次都整份丢失**；
* **目录枚举**（`dir-listings.txt`）：DLSS5 目录 / ReShade 覆盖目录 / 游戏目录各一份清单 + `.addon`/`.addon64` 同名检查；
* **游戏目录：我们以为的 vs 实际跑的**（含 XXMI `game_folder` 与在跑进程的命令行）；
* **XXMI 注入现场**：每次启动的 `exe`/`work_dir`、每个 dll 的注入结果、`Stopping process` 次数、XXMI 自己报的错（从 200 KB 原始日志解析成字段）；
* **"没有 WER / 没有 Unity 崩溃"也留一条 manifest**（以前空结果不留痕，"没崩"和"没去抓"分不开）；
* **退出码表补 `0xC000013A`**，并给 `0xC0000409 / 0x40000015` 标注"会弹 Runtime Error 对话框"；同时**修正原来那句不完整的判据**（"没有事件 ⇒ 不是自己崩的"——CRT 弹框会把进程卡住、既不写事件也不退出）。

## 四、新增：热重载（游戏运行中改配置 + F10）

启动页在**终末地运行中**会把按钮区切成左右两个：左「一键启动」、右「热重载」；**没运行**时保持原来的整宽单按钮。

点热重载会：**按当前勾选重铺 staging**（关掉的移出 `Mods\`、新打开的铺进去）→ 跑 `prepare_launch`（收编手动 Mod + 同步注入库 + 初始化自检）→ 给游戏窗口 **发 F10**。

实现上的三处要点（都撞过）：

* **必须 `SendInput` 真实按键**：3DMigoto/EFMI 每帧轮询 `GetAsyncKeyState`，投窗口消息收不到；
* **按下要保持 180ms 并补发一次**：按键持续时间≈0 时，一帧 16ms 的轮询会**整帧错过**；
* **游戏窗口必须是前台**（`check_foreground_window` 默认开），且**候选窗口按进程名 + 剔除覆盖层 + 优先 `UnityWndClass`** 选——否则会把 F10 发给 Poser 的覆盖层窗口（实测踩到）。
  * 日志会写明**候选窗口、最终选中项、是否拿到前台、以及 `d3dx_user.ini` 有没有被 3DMigoto 更新**（= F10 真的被处理了）。

## 五、其他

* **DLSS5 目录缺底座会自愈**：先在候选位置找（默认 `runtime\dlss5`、`runtime\reshade`、DLSS5 目录的**上一级**、游戏目录…），都找不到才联网下载；`d3d12.dll` 还会校验"确实是 ReShade 载荷"；
* **游戏目录以 XXMI 实际启动的那份为准**：净化 / 文件守护 / ngx 运行库部署 / OptiScaler 隔离按需启用该判据（只读探测行为不变），并在自检里报一条 `game_dir:mismatch`；
* **版本号约定**：未发版时本地写 `<最新 Release + 1>-beta`，**同号时正式版更新**（`1.0.9` 比 `1.0.9-beta` 新），发 Release 一律不带 beta；版本比较收敛到 `version.parse_version` 一处口径。

**测试**：`pytest tests -q` 743 passed（另含新增的热重载回归测试）。
