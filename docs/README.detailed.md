# EndfieldModController —— 详细文档

> 这是**详细版**：安装细节、数据与目录结构、逐项故障排查、开发与发布流程都在这里。
> 只想正常使用的话，看简略版就够了 → **[README.md](../README.md)**

《明日方舟：终末地》的一站式 Mod 管理器：把 **DLSS5 神经渲染 + 第一人称视角 + 服装 Mod（EFMI）** 以及 **乳摇（SecondaryMotion）** 统一到一次「一键启动」里，并自动维护各项注入与初始化自检。

Windows 桌面程序（Python + PyWebview），单文件 exe，**零配置启动即用**。当前版本 **1.0.22**。

> 💬 **QQ 群：1045239747**（加群验证答案 `jing_hy`）—— 不方便用 GitHub 或想直接问，都可以在群里发诊断包；记得附上现象。

> 本程序**只做编排与自检**：注入由 XXMI Launcher 完成，服装 Mod 由 EFMI 加载，神经渲染与第一人称是挂在同一个 ReShade 底座下的 addon。
> 它**不改游戏本体文件**，也不内置任何 Mod —— Mod 都是你自己放进来的。

---

## 一、它能做到什么

| 能力 | 说明 |
| --- | --- |
| **从零装好运行环境** | 首次启动自动下载并安装 XXMI Launcher、XXMI Libraries、EFMI 三个组件（Release 资产带 sha256 校验），装完写好配置 |
| **Mod 库管理** | 把 `.zip` / `.7z` / `.rar` **拖到页面任意处**即可导入；自动解压进库、尝试识别角色归属（中文名 / 社区昵称 / 英文代号 / 拼音），认不出就直接弹窗让你选（下拉按"最可能的角色"**预识别**）；卡片的「⋯」里还能**更换 Mod 归属** |
| **Mod 下载** | Mod 库页「下载 Mod」：**粘贴直链**（一行一个）→ **并行下载**（每个任务内部走 fastnet：慢时并发分块、直连不通自动换线路、断点续传）→ **能解压的（zip / 7z / rar）自动解压进库**并识别角色；**不能解压的留在临时目录**并告诉你路径。落点 `<数据根>\runtime\downloads\`，**不直接写 Mod 库** |
| **同角色互斥** | 同一个角色只保留一个 Mod，避免 EFMI 同时加载两个同角色 Mod 把游戏搞崩 |
| **收编手动 Mod** | 你自己丢进 `Mods` 目录的 Mod 会被认出来、收进库并在界面勾选上 |
| **一键启动** | 维护 XXMI 的注入库（DLSS5 的 `d3d12.dll` + EFMI 的 `d3d11.dll`）、补齐缺失组件、跑完整初始化自检，然后拉起 XXMI |
| **插件开关** | DLSS5、第一人称、**皮肤 Mod**、乳摇注入，都能单独开关。⚠️「**皮肤 Mod**」这个总开关**不是**"停掉 EFMI 注入"—— 用户实测那样终末地会**直接拉不起来**；它只表示"**一个皮肤都不加载**"（EFMI 的 `d3d11.dll` 始终注入，`Mods` 目录清空，随时开回来）。 |
| **DLSS5 自检** | 检查并补齐 shader 编译依赖、ReShade 标准头、纹理目录、preset 里的 technique 与运动矢量来源 —— 这几项缺任何一项都会"看起来都装了，就是不出帧" |
| **乳摇开箱可用** | 自动实例化管理器的模板文件、纠正 `enabled` 开关、并预写 `settings.json` 记住游戏目录（不再每次让你选文件夹） |
| **乳摇角色数据自动补齐** | 上游 Release 的角色数据常常落后于它的仓库（例如**提弗洛斯**只在 `main` 里、发行包里没有）→ 程序每次启动后在**后台**从仓库拉一次，**只补你本地缺的角色**，绝不动你调过的幅度/频率，也不碰 `presets\User.json`；来源可用 `sbm_data_source` 指向你自己 fork 的仓库（改完 push 即生效） |
| **辅助 Mod 页** | 不换装、只改行为的小 Mod（如「隐藏 UI＆UID」按 `alt 1`）单独一页管理：**不属于任何角色、不参与同角色互斥**、也不会被要求"确认角色归属"。自动识别 = 没有换装资源 +（名字含隐藏/辅助/UI/HUD 等 或 ini 是 `handling = skip` 型）+ 归不到任何角色；认错了可在卡片「⋯」里一键改成角色 Mod |
| **NGX 冲突自动处理** | 检测到第三方 NGX 注入器（例如 OptiScaler 用 `winhttp.dll` 截获进程里所有 NGX 调用）会**自动备份并移走**它 —— 这类注入器会让 DLSS5 的神经渲染**一帧都出不来**（面板表现为「成功 NR 帧 0」/`0xBAD00001`），而正常用户不会去看日志去发现这一点，所以这里不提示、直接处理；备份可还原 |
| **自带 DLSS 的游戏自动停用喂帧组件** | 终末地**自带 DLSS**（游戏目录有 `sl.interposer.dll`），而喂帧组件（`dlss5-feed`）是给"没有 DLSS 的游戏"用的、还会与游戏自己的 DLSS 抢同一条 NGX 链路 → 自检时**自动把它停用**（移到 `runtime\dlss5\_disabled\`，可逆、不动 preset/shader）。设置页有开关可关掉这个行为（关掉后下次自检会自动放回） |
| **游戏目录净化 / 还原** | 把第三方注入物**先备份再移走**（`runtime/game_backup/…`），随时一键还原；被移走的系统模块会自动从 System32 补回。**认识的不只是我们自己的注入**：第三方注入器（例如 OptiScaler 用 `winhttp.dll` 顶替系统模块）同样会被识别并移走，连它的 `OptiScaler.ini` / `.log` 一起（2026-10-01 起） |
| **诊断与日志** | 启动日志、崩溃监视、一键导出诊断 zip（含日志、注入状态、Windows 事件、**DLSS5 现场 `dlss5-feed.log`**） |
| **崩溃归因** | 崩溃包会带 `cause.json`：**自检记录过 Mod 资源冲突时，弹窗专门提示去清冲突**（区别于其它崩溃，主按钮直接跳到 Mod 库）；同时自检会校验 `runtime\dlss5` 里的随包组件是否被别的整合包换过/换坏，**发现偏离基线就自动按基线重新展开**（原文件备份为 `*.bak-before-baseline-restore`）—— 这类损坏的表现常常是"游戏每次启动几十秒后崩在显卡着色器编译器"，而文件看着都齐 |
| **启动前风险确认（只提示）** | 一键启动在**拉起 XXMI 之前**先查"这套 Mod 会不会崩"：① 自检的资源冲突；② **崩溃记忆**（`runtime\_state\crash_memory.json`，记下每次崩溃时的 Mod 组合）。有风险就弹窗说清是什么冲突，由你选「**先去清理，不启动**」（右侧橙色主按钮、默认聚焦）/「仍然启动」。**这里只做提示**：程序不会替你改勾选 —— 需要一键处理时去下面的「皮肤冲突自动处理」 |
| **游戏内 Mod 控制面板** | 启动页「游戏内 Mod 面板」打开后，把自研 ReShade addon 与动作清单放进 **ReShade 真正会读的目录**（进游戏按 `Home` → **ModeController** 页）。面板按**角色 → Mod** 分栏，**每一项就是一个按钮**：点一下 = **按一次这个 Mod 自己的那个键**（Mod 内部切到下一档），旁边标出 `变量名`、`推测含义`、`手按哪个键`、生效条件。⚠️ **不再锁 Mod 按键**（锁键会把 Mod 的 `key` 改写成 `VK_F24`，面板再发原键就没人接），所以你手按原来的键照样能用 |
| **皮肤冲突自动处理（崩溃后）** | 终末地因为**皮肤（Mod）资源冲突**崩掉、且崩溃归因判定为 Mod 冲突时，崩溃弹窗里给「**一键关闭其中一个（自行选择）**」→ 点它先关掉原弹窗，再弹「选择要保留的 Mod」：**每组冲突一个下拉框**（默认保留第一个），点「保留所选并重新生成控制器」就会自动取消勾选其余那些并重跑一次生成控制器。**只改勾选，绝不动你的 Mod 文件**；库里定位不到的组（手动放进 Mods 的）只提示、不硬处理 |
| **Mod 修复 / 回滚 / 移出库（实验性）** | Mod 卡片**右下角「⋯」**：用社区修复工具（**B站 up 主 可可HXL**《终末地Mod修复工具包》v1.5）把 ini 里的资源槽位号适配当前游戏版本；**改前整份备份、可一键回滚**；删除 = 移出库（进 `runtime\backups\mod-trash`，可找回）。库页顶部还有**「一键修复所有 Mod」**（后台跑、已修过的跳过） |
| **角色表跟官网** | 角色识别用的表**每次启动后在后台非阻塞**地跟官网干员页对一次（24 小时内不重复请求）：官网上了新干员就自动更新到 `<数据根>\runtime\_state\characters.json`（**不改随包那份、社区简称不丢**）；也可手工跑 `python scripts\fetch_characters.py` 核对/更新 |
| **更新** | 检查/下载新版并自更新（下载后校验 sha256，退出后由脚本替换并重启）；组件（XXMI / EFMI / 乳摇）也能单独更新 |
| **下载兜底** | 内置轻量加速：慢/抖时临时并发分块，直连不通时临时换镜像线路 —— 按需启用、用完即放，不装证书、不改系统 |
| **摆姿 / MMD 播放（Endfield Poser）** | 从它的官方 Release 下载安装包，调用**它自己的安装向导**把文件装进游戏目录（不随包分发、不改它的包）；开关只改文件名（可逆）；状态与日志在设置页，摆姿用它自带的页面 `http://127.0.0.1:18923` |

### Mod 下载（粘贴网址 → 并行下载 → 自动解压入库）

用户 2026-10-02 原话：「在 mod 库页按钮下面加一个 mod 下载，**下载进临时文件夹**，
**能解压的解压进库**，**不能解压的提示用户需要手动解压**，**并行多线程下载**」，
下载源 = 「**给个输入框输入网址**」（不是内置清单）。落地（`endfieldmodcontroller/moddl.py` + `api.py` 三个方法）：

1. **输入**：Mod 库页「下载 Mod」按钮 → 弹窗里一个输入框，**一行一个** `http(s)` 直链
   （非 http/https 一律丢掉 —— 免得"下载"变成"从本机任意路径取文件"）；链接去重且保持顺序。
2. **并行**：`ThreadPoolExecutor`（最多 4 个任务同时跑）；每个任务内部再走
   `dependencies._http_get` → `fastnet.download`（慢时**临时**并发分块、直连不通**临时**换镜像线路、
   断点续传、sha256 校验）—— 那套用完即放，不留后台线程、不改系统。
3. **落地**：先下到 `<数据根>\runtime\downloads\`（**临时文件夹**，不直接写库）。
4. **入库**：`.zip` / `.7z` / `.rar` 交给 `api._import_archive_file()` —— **与拖入 zip 完全同一条链路**
   （zip-slip 校验、自动提层、重名加后缀、收编、角色识别），所以"下载进来"和"拖进来"结果一致。
   ⚠️ **下载并行、解压入库串行**（同一把锁）：两个包同时往库里写会让"重名加后缀"的判断互相打架。
5. **不能解压的**（非 zip/7z/rar，或包本身坏了）：**不清文件**，标成「需手动解压」，
   把路径写在界面上，并给「打开下载目录」按钮 —— 程序不猜、也不假装处理了。
6. **失败**如实报（HTTP 错误 / 校验失败 / 磁盘问题一律显示原因），一批结束给汇总：
   `入库 N · 需手动解压 M · 失败 K`；有入库的会顺手刷新 Mod 库，新 Mod 立刻可见。

#### 香蕉网（GameBanana）适配

用户 2026-10-02 原话：「我还要对香蕉网做适配，你看看能不能看到网址是香蕉网，比如
`https://gamebanana.com/mods/721442`，就**拉取资源同时拉取一张图片**，然后**如果访问不上，
就弹窗提示无法访问，建议检查 vpn**」。

* **识别**：`gamebanana.com` 的 `/mods/<id>`、`/mods/download/<id>`、`/dl/<id>` 都认；别的站点一律当普通直链。
* **为什么不抓网页**：那个页面是前端渲染的，HTML 里没有下载地址。改走官方 **`apiv11`**
  （`https://gamebanana.com/apiv11/Mod/<id>/ProfilePage`），一次拿到：Mod 标题、**每个文件的真实下载直链**
  （`_aFiles[]._sDownloadUrl`，形如 `https://gamebanana.com/dl/<文件id>`）、**封面图**（`_aPreviewMedia`）、
  所属游戏（顺手校验"是不是终末地的 Mod"）、作者、版本、点赞数。
* **取哪个文件**：一个提交可能有多个版本 —— 取**最新的那个**（`_aFiles` 里第一个非归档项），
  并在任务里注明「共 N 个文件，已取最新那个」。
* **封面图**：下到临时目录，并在任务行里显示缩略图（后端转成 **data URI** 送前端 ——
  WebView2 里 `file://` 读本地图片会被拦）。**图下不到不算任务失败**（它只是锦上添花）。
* **访问不上**：网络层异常（超时 / DNS / 证书 / 地区限制）统一包成 `moddl.GameBananaUnreachable`
  → 该任务标 `unreachable` → 前端**弹窗**「访问不上香蕉网…建议检查 VPN 或加速器后重试」，
  而**同一批里的其它链接照常完成**（一个失败不牵连别人）。

### 游戏内 Mod 控制面板细节

**开关**：启动页最后一行「**游戏内 Mod 面板**」（config 字段 `hotkey_takeover`，默认 **true**）。
打开后做两件事：

1. **注入面板** —— 把自研 ReShade addon 与动作清单放进 **ReShade 真正会读的目录**。
   这一点以前错过：ReShade 6.8 的日志写死了它只搜 `d3d12.dll` 所在目录
   （`Searching for add-ons (*.addon, *.addon64) in '<base>'`），所以 xxmi_extra 注入方式下
   正确位置是 `<数据根>\runtime\dlss5\`。面板文件：

   | 文件 | 作用 |
   | --- | --- |
   | `endfieldmodcontroller.addon64` | 面板本体（随 exe 打包，`assets\addon\` 里那份） |
   | `actions.tsv` | 动作清单（每行一项；`hint`/`key_label`/`char_group`/`condition` 是 2026-10-01 追加的 4 列） |
   | `user_ini_path.txt` | EFMI 的 `d3dx_user.ini` 路径（面板据此显示状态） |
   | `panel_info.txt` | 面板状态：`takeover` / `actions` / `generated`。⚠️ `takeover` **只有一个含义：Mod 原键是否真被锁住** —— 锁键停用后它恒为 `0`，面板据此不再显示"原键被锁、面板按键不会生效"那条警告 |
   | `modecontroller.addon.log` | 面板自己的日志（加载、把 EFMI 的读键接到哪个模块、每次按键） |
2. **展开动作清单** —— 每个 Mod 的 `[Key*]` 段被解析成面板上的一项，带上推测含义（`hint`）、
   按键（`key_label`）、角色分组（`char_group`）与生效条件（`condition`）。

⚠️ **不再锁 Mod 按键**（2026-10-02）：面板改成**直接发 Mod 自己的原键**，而锁键会把 `key` 行
改写成 `VK_F24`、面板发的原键就没人接了 ⇒ 两者互斥。所以 `core.patch_mod_hotkeys` 整套动作由
模块开关 **`core.HOTKEY_LOCK_ENABLED`（现为 `False`）** 停用：
**判据、代码、备份/回滚链路全部保留**，改回 `True` 即复活，
`tests/test_activation.py` 里有一条"翻回 True 仍然照旧改写 + 库原件零改动"的用例钉着它没有腐烂。

**面板上的每一项 = 一个按钮**（用户 2026-10-02：「不要用开关或滑块，都是一个键，做切换的按键
就行」）：点一下 = **按一次这个 Mod 自己的那个键**（Mod 内部切到下一档）；想连切几档就连点几下
（点完面板不会自己关）。面板**不显示开/关状态** —— 那个状态活在 3DMigoto 的内存里（只有游戏
退出时才写回 `d3dx_user.ini`），任何"开 / 关"显示都是编的，而用户对"表面功夫"的容忍度是零。

**"推测含义"是怎么来的**（`endfieldmodcontroller/hotkey_hints.py` +
`hotkey_hints.json`，后者由 `scripts\gen_hotkey_hints.py` 扫 Mod 目录生成、可手工增删）：
① 变量名命中词表（`ear → 耳羽`）；② 变量名拆词后命中（`draw_component_0_zfy_head_horns → 头/角`）；
③ ini 里引用该变量的 `if` 块附近的 `; [mesh:…]` 注释 / `Resource-*` 名字命中词表
（佩丽卡的 `$ear` 旁边就写着 `hair_ear_copy`）；④ section 名（`KeyToggleUI → 控制菜单`）；
⑤ 都推不出时**不编造中文**，退回变量名清洗后的英文短语（`head horns`）。

**中文显示**：ReShade 默认字体（ProggyClean）没有中文字形。打开这个开关时，如果
`ReShade.ini` 的 `[STYLE] Font` 还是空的，程序会自动指向系统中文字体（`msyh.ttc` 等，
写前备份 `.bak-before-panel-font`；config 字段 `reshade_panel_font` 可关掉）。
真的拿不到中文字形时，面板**自动改用英文标签**（写入 `modecontroller.addon.log`）。

**安全底线**：`launcher.resolve_hotkey_takeover()` 会先确认"ReShade 注入开着 + 底座在位 +
面板文件齐 + 写盘成功"，任何一条不满足都把原因写进日志与界面。⚠️ 2026-10-02 起它**恒返回
False**（返回值是 `stage_and_prepare(hotkey_takeover=...)` 用的，而锁键已停用）——
它仍然负责"面板到底铺上没有"，只是不再据此去锁用户的按键。

### Mod 备份仓（只增不减）

用户 2026-10-01 原话：「在**根目录下放一个文件夹做 mod 备份**，这个文件夹**只增不减**，
**只要见到新 mod，就打包 zip 放进去**」；随后又改成「**改成不要打包，纯备份**」—— 现在是**纯复制**：一个 Mod 一个文件夹，原样躺进备份仓。

* **位置**：默认 `<数据根>\mod-backup\`（与 `library\` / `runtime\` 平级，就在 exe 旁边）。
  **想换地方**（2026-10-02 用户要求「加个 mod 备份在设置里能自行选择备份目录」）：设置页
  ① 组里的「**Mod 备份目录**」直接填路径（支持 `D:\...` 绝对路径），或点旁边的「**选择…**」
  弹出系统文件夹选择框挑一个；**留空 = 回到默认**。改完立刻生效，但**旧目录里的备份原地
  留着**（"只增不减"对"换目录"同样成立），新目录会在下一次扫描后重新整份备份一份。
  填成 Mod 库/中转目录里的路径会被**当场拒绝**并说明原因（见下一条）。
* **时机**：启动后的后台预热 + 每次「重新扫描」之后各跑一次；只处理**还没备份过**的 Mod，
  所以之后的启动是毫秒级。扫描/复制都在后台线程，不卡界面。
* **只增不减**：`modbackup.py` **没有任何删除或覆盖已有备份的代码路径**；同名备份目录
  已存在就只登记进索引（`<备份仓>\_index.json`）、绝不重拷 —— 索引丢了或坏了也不会把
  好备份覆盖掉（按"目录已存在"重新登记）。早先打包时代留下的 `.zip` 也**原样留着**，
  并且同样算"已备份"，不会再复制一份目录出来。
* **失败不中断**：一个 Mod 复制失败只记一笔（`WARN Mod 备份失败：…`），整批继续。
* **绝不碰库**：只读 `library\`、只写备份仓；若备份目录与库/中转目录**重叠**，整体拒绝执行
  （否则备份会落进库里越滚越大），界面会提示改 `mod_backup_dir`。
* **纯复制、不打包**：一个 Mod 一个文件夹，原样躺在备份仓里（先复制到 `_copying_xxx`
  临时目录、成功后再改名 —— 中途失败不会在备份仓里留下半份"看起来备份了"的东西）。

### 依赖（RabbitFX / Orfix / Slotfix）：按需激活 + 去重 + 内外优先级

* **什么是依赖**：像 **EFMI RabbitFX** 这种"shader 特效前置"—— 服装 Mod 通过
  `Resource\RabbitFX\FXMap = ref …` 这类写法引用它。控制器不把它当皮肤 Mod，而是统一放在
  `<Mod 库>\_deps\<名字>` 下维护（来源与版本写在 `dependencies.json`）。
* **按需激活**：**只有被勾选的 Mod 真的引用了它**，才会被放进 `EFMI\Mods`。判据只有**一个**
  函数（`core.collect_required_dependency_names`）：既读 `mod.meta.json` 的 `requires`，
  也**扫 Mod 的 ini 文本**里有没有出现依赖的名字（扫之前剔掉 `CommandList\X\Y` 这种 ini
  内部引用，免得把 `SlotFix` 误报成缺失）。
  ⚠️ 2026-10-02 修：以前"决定要不要下载"用扫 ini、"决定要不要激活"只读 sidecar 的
  `requires`，两套判据 ⇒ 依赖**下得来、进不去**（下载了也不生效）。现在两处共用一套。
* **只允许一份生效**：RabbitFX 作者在发布页写死过「Having multiple RabbitFXs will cause
  unexpected behaviours and game crashes… only ever have **one instance**」。所以程序对每个
  依赖都**只放一份**进 staging，其余**屏蔽** —— 注意是"不加载"，**不删你的文件**。
* **内部 / 外部与优先级**（设置页 ⑤「**依赖优先用内部那份**」，**默认开**）：
  * **内部** = 控制器自己维护的 `<库>\_deps\<名字>`；**外部** = 你手动放进库里的
    （名字常带 `（重要前置）…` 前缀、里面还套一层）。
  * 开着（默认）= **内部优先**：进 staging 的是内部那份，外部整侧屏蔽；
  * 关掉 = **外部优先**：进 staging 的是外部那份，内部屏蔽；
  * 同一侧有多份 → **只启用"最后安装的那一份"**（按目录创建时间判断）；
  * 日志里会把账写清楚：`依赖启用：rabbitfx → RabbitFX`、`依赖去重：屏蔽「…」（…）`。

### DLSS5「成功 NR 帧 = 0」时先看这里

自检里有一项 `dlss5:nr_binding`（读**最近一次**运行的 `runtime\dlss5\ReShade.log`，只认最后一次，
不拿历史成功记录充数）。

**先排除三个"看着像原因、其实不是"的**（2026-10-01 逐一验证过）：

* ❌ `NR upscaling is not applicable: the game's DLSS already renders at output resolution`
  —— 这**只是一条 INFO**，DLAA / 原生档位下必然出现，而 DLSS5 在那种情况下**照常出帧**
  （日志里 `created inline NR resources 3840x2160 -> 3840x2160 (native)` 与
  `inline feature 18 evaluation succeeded` 是同时成立的）。别据此让用户去改超分档位 ——
  2026-10-01 我就在这里判错过一次，被用户当场纠正（他原话：「我用的 dlaa 也能正常使用」）。
* ❌ 驱动版本：同版本驱动（`32.0.16.1714`）的另一台机器上就是正常的。
* ❌ 运行库：`nvngx_dlssnr.dll` 与随包基线 sha256 一致、`signed DLSSNR 310.8.0 D3D12 runtime
  initialized` 也打过 —— 说明它**初始化成功了**。

**真正的失败信号**是 `feature 18 create failed with 0xbad00001`（面板表现为 `成功NR帧 0` /
`最新NR NGX结果 0xBAD00001` / `超分: 请求ON｜活动OFF`）。能确认的是：运行库初始化过、NR 资源也
建好了，**只有 NGX 拒绝创建 feature**。排查顺序（按可能性）：

1. **显存预算**：把游戏分辨率 / 渲染比例调低一档再进（8 GB 显存的笔记本尤其值得试）；
2. **虚拟显示适配器**：关掉 ToDesk / 向日葵 / 模拟器这类虚拟显示适配器与其它占显存的程序；
3. 仍不行 → 把 `ReShade.log` 里 `feature 18 create failed` **前后 20 行**发出来。

若是第三方 NGX 注入器（OptiScaler）截走 NGX，程序会**自动备份移走**它（见上表「NGX 冲突自动处理」）。

### 「游戏内 Mod 面板」的默认值

**默认开启**（`config.hotkey_takeover`，2026-10-01 用户要求「把快捷键整合
设为默认开启」）：装完即用，不必先去设置页找开关。老配置里存着显式的 `false` —— 光改默认值
对它们无效，所以 `AppConfig.load()` 里做**一次性迁移**（`hotkey_default_applied` 标记）：
迁移过一次之后，用户自己关掉就不会再被改回来。

⚠️ **2026-10-02 语义变更**：这个开关现在只表示"**要不要把面板铺进 ReShade**" ——
"锁住 Mod 按键"那半已经停用（见 `core.HOTKEY_LOCK_ENABLED` 的说明：面板改成直接发 Mod 原键，
锁键会让它失效）。关掉开关时**已经铺好的面板文件不删**，只是下次启动不再铺。

**DLSS5 的默认开关按显卡支持范围决定** —— 判据的唯一实现在 `deviceinfo.dlss5_supported()`：
**NVIDIA 且型号名含 `RTX`（= 有 tensor core）⇒ RTX 20 系及以上都支持**。

判据两度变更，别把它们弄混：

* **2026-10-01**（用户原话「开启时检测机器，如果不是 50 系就默认关 dlss5，开启 dlss5 的
  时候弹窗说明拒绝」）：当时 DLSS5 首发只有 50 系运行库，40 系及更早在 NGX 层会被
  `0xBAD00001`（FeatureNotSupported）拒掉 ⇒ 非 50 系一律默认关 + 拒绝手动开。
* **2026-10-05**（用户原话「**去掉所有对非 50 系的锁，换成对 a 卡和 10 系及以下和核显**」）：
  实测发现随包那份运行库**只含 sm_120 内核**（这正是 40 系必然失败的根因），而社区把它重定向
  到 sm_89 / sm_86 / sm_75 之后 40/30/20 系都能跑 ⇒ 支持范围扩大为"有 tensor core 的 RTX"，
  并**按显卡架构自动选运行库**（见下一节）。

迁移：`dlss5_gpu_scope_applied` 是一次性标记 —— 老 40 系用户配置里的 `False` 是**旧判据**
写进去的，会被替他们**打开**；50 系用户自己关掉的不动（旧判据本来就支持 50 系，那个 `False`
只可能是用户设的）。不支持的机器（GTX 10/16 系、A 卡、核显）仍默认关，手动去开会被后端拒绝
（`set_component_addon` 返回 `rejected: dlss5_unsupported_gpu`），自检项 `dlss5:gpu_support`
也会如实说明"这是硬件前提、不是配置问题"。

### 运行库按显卡架构自动切换（2026-10-05）

DLSS5 的神经渲染代码跑在 `nvngx_dlssnr.dll` 里，而那份运行库**按 CUDA 架构分别编译**。
程序按本机显卡架构**自动选一份**落成 `runtime\dlss5\nvngx_dlssnr.dll`（NGX 与 addon 只认
这个名字 —— 变体只体现在**内容**上）：

| 变体 | 内含内核（实测 fatbin） | 给谁 | 来源 |
|---|---|---|---|
| `official` | sm_120 | RTX 50 系 | NVIDIA 官方 `310.8.0`（**随包**） |
| `sf` | sm_75 / 86 / 89 / 120 | RTX 20 / 30 / 40 系 | 社区镜像 `RankFTW/rhi-repo` 的 `310.8.SF-v2`（**随包**） |
| `rtx40` | sm_89 / 120 | RTX 40 系（可选优化） | 同镜像 `310.8.0-RTX40`（**依赖页按需下载**） |

* **随包两份即可覆盖全部受支持型号** ⇒ 一键启动**永远不需要为运行库下载任何东西**，
  而且四种机器的动作序列与耗时同量级（自检**只展开选中那一份**，不会白解压第二份 165 MB）；
* `rtx40` 是 40 系"更贴合 Ada"的版本，**不装也完整可用**（`sf` 含 sm_89）；装了之后一键启动
  会自动切到它，用户不需要做任何额外操作；
* **判据只有一处**：`runtime_assets.dll_architectures()` 读文件里的 fatbin 记录 ↔
  `deviceinfo.best_rtx_sm()`。换显卡、被整合包替换文件、双卡换主卡都会**自动切回**
  （自检项 `dlss5:nr_arch`），旧文件留 `.bak-*` 可回退；
* 基线检查（`baseline_mismatches`）**按"本机生效的那一份"判** —— 否则 40 系上刚装好的 `sf`
  会被判成"偏离随包基线"、被自动换回 `official`、下次再判不符，**每次启动来回替换 165 MB**。

**依赖页**另有两件事：一行「随包资产包（assets-bundle.zip）」= **导入本地 zip**（或从 Release
下载）—— 单文件 exe 用户、离线机器、以及从社区镜像下了单份运行库 zip 的场景都用它（单份
运行库 zip 会**按内含架构自动识别变体**）；40 系机器上还会多一行「DLSS NR 运行库 · RTX 40
优化版（可选）」，未安装标灰而不是标红（它缺失是正常状态）。

### 面板的按键是怎么送进游戏的（进程内伪造读键 + F13..F24 内部通道）

**一句话**：面板**不发任何输入事件**。它和 EFMI 在**同一个进程**里（ReShade addon 与
3DMigoto 都注入到游戏进程），所以直接在进程内让 EFMI 的读键调用"看到" **F13..F24** 被按下；
`controller.ini` 收到动作号后用 `run =` **呼叫注入在 Mod 自己 ini 里**的那段命令列表来切档
—— **全程不碰任何真实按键**，所以不会连带触发绑了同一个真实键的别的 Mod / 别的插件。

**为什么"切档"要写在 Mod 那边**（2026-10-02 的实测结论）：`[CommandList]` 里的变量赋值
**只认本 ini 声明过的名字**，带路径的跨命名空间赋值（`$\mods\...\coat = 1`）会被**静默丢弃**
—— 现场证据：同一个段里本命名空间的 `$mc_action_seen` 生效、**11 个 Mod 变量引用全部无效**；
而跨命名空间**调用命令列表**是 3DMigoto 支持的（源码 `ParseRunExplicitCommandList` +
`get_namespaced_section_name_lower`）。所以注入的是 `[CommandListMC_Panel<N>]`，里面用
**Mod 声明时的原样大小写**（`$backSkirt` —— ini 层变量名大小写敏感）。

**为什么不能"发键"**（2026-10-01 ~ 10-02 的实测，别再走回去）：

* 合成输入（`SendInput`）在终末地里**完全无效**：三批对照探针（带修饰键的 `F13..F24` /
  带修饰键的 `F1..F12` / **不带**修饰键的 `F13..F24`）**全部 0 触发**，而用户手按 Mod 自带键
  一切正常，`SendInput` 返回值却正常 ⇒ 合成输入在进入游戏进程之前就被吞掉了。
  `SendInput` / `keybd_event` / `PostMessage` 走的是同一条路，不值得再试。

**做法**（`reshade_addon/src/vkey_inject.h` + `core.inject_panel_lists`）：

1. 面板加载时在进程里找到 **EFMI 的 `d3d11.dll`**（3DMigoto 的注入 proxy）；
   判据是"**它导入了 `GetAsyncKeyState`**"—— 实测这个 dll 里键盘读键**只有这一个入口**
   （没有 raw input、没有 DirectInput 键盘），所以接住它就等于接住了 EFMI 的读键；
2. 遍历该模块的**导入表**，把 `GetAsyncKeyState` 那一项换成我们自己的函数
   （**IAT hook**：不改任何代码字节、不碰游戏本体的代码、也**不影响别的调用者**）；
3. 点按钮 → 发一串**内部键**：动作号的十进制各位（`F13+n` = 数字 n，覆盖 F13..F22）+
   最后 **`F24` 提交**，**全程不带任何修饰键**（用户 2026-10-02 原话：「**不要用 alt 这种辅助键**」）。
   * 一帧一个键地发（`160ms` 按下 + `140ms` 间隔）：EFMI 是每帧轮询的，同时按下两位数字会被
     当成一次组合、数字位错乱；发送期间再点按钮就把动作**排到队尾**（连点 = 连切几档）。
   * 窗口内**第一帧**返回 `0x8001`（"正按住 + 刚按下"），之后只返回 `0x8000` ——
     两种常见读法都只触发**一次**，不会一次点击连切好几档。
   * `controller.ini` 的 `[CommandListMC_Commit]` 收到动作号后 `run = CommandList\<Mod 命名空间>\MC_Panel<N>`；
     那段（注入在 Mod ini 末尾）把变量**从当前值切到列表里的下一个值**（末尾回到第一个，
     `else` 兜底）。所以面板**不需要知道档位**，你手按改过的档位也不会和面板打架。

**⚠️ 这条路走了三步（2026-10-02，留档，别再绕）**：

1. `F13..F24` + **在 `controller.ini` 里直接改 Mod 变量** ⇒ 失败：那种跨命名空间赋值被静默丢弃
   （同段里本命名空间的 `$mc_action_seen` 却正常自增 —— **假绿灯**；判据必须落在"Mod 的变量
   到底有没有变"上）；
2. 改成**发 Mod 原键** ⇒ 能用（用户实测"这个可以"），但会连带触发绑了同一个真实键的别的 Mod
   —— 面板本该"只动自己那一份"；
3. 现在这版：`F13..F24` + **把切档逻辑注入进 Mod 自己的（staging）ini**，`controller.ini` 只
   `run =` 呼叫它。顺带更正当天的一个误判：**ini 层变量名大小写敏感**，引用要用 Mod 声明时的
   **原样**（`$backSkirt`；写成 `$backskirt` 会被当成未声明变量）—— `d3dx_user.ini` 里那些小写是
   **持久化层**的规范化形式，不能反推成 ini 的书写规则（EFMI 官方模板里的 `$\EFMIv1\required_version`
   也是原样）。

**面板顶部有一行状态**：`注入 OK · EFMI 命中 N · 面板已发 M 次`。点按钮后"命中"会涨
⇒ hook 确实走在 EFMI 的读键路径上（**可自证**）；一直是 0 说明这条链路没接上（日志里有原因）。
自检项 `panel:hotkey_conflicts` 就是读 EFMI `d3d11.dll` 的导入表来判断这条通路的
（顺带保留旧判据：ReShade / 其它 addon 若占了 `F13..F24`，仍然照报）。

**离线自测**：`python scripts\test_addon_hook.py` —— 造一个"假 EFMI"（只通过导入表轮询
`GetAsyncKeyState`，与真 EFMI 同一种读法）让宿主加载它，验证 21 条断言：注入被读到、跨帧保持、
"刚按下"只出现一次、修饰键 + 主键组合、到点自动释放、**只影响目标模块**、未注入的键原样透传、
卸载时导入表恢复原样。`tests/test_addon_hook.py` 是它的 pytest 外壳（编译器不在就 skip）。

另外：**面板操作不会自动关闭 overlay**（旧实现每次操作都调 `open_overlay(false)`，用户感受是
「按一个键就会退出 ReShade 页面」，连点几下都做不到）。

### 注入链（同一进程内同时生效）
```text
唯一的 ReShade 底座  runtime\dlss5\d3d12.dll（ReShade 6.8.0 Addon 版）
  ├─ renodx-dlss5-4.7_汉化.addon64      → DLSS5 神经渲染
  ├─ renodx-endfield-enhancer.addon64   → 第一人称 / 相机
  ├─ dlss5-feed.addon64                 → 给 DLSS5 喂"颜色 + 运动矢量 + 深度"
  ├─ trans-zh.addon64                   → 面板汉化
  └─ reshade-shaders\                   → DLSS5_Feed.fx、iMMERSE、ReShade 标准头
服装 Mod 引擎  EFMI\d3d11.dll
乳摇注入       游戏目录的 d3dcompiler_47.dll / vulkan-1.dll（代理）+ plugin\sbm.dll
摆姿 / MMD     同一个 d3dcompiler_47.dll 代理（加载 plugin 下所有 dll）+ plugin\poser.dll
```

XXMI Launcher 启动游戏时按「注入库」注入上表里的 DLL，注入库由本程序维护，启动页的开关就是它的快捷切换。
**一个游戏进程只能有一个 ReShade 底座**，所以不要把两个 `d3d12.dll` 同时注入。

---

## 二、运行与安装

### 方式 A：直接双击 exe（推荐）

1. 下载 `EndfieldModController.exe`（Release 里 exe 只有这一个文件，另有一个 `assets-bundle.zip`）；
2. 放到一个**你有写权限的目录**（见下方"数据根"），双击；
3. exe 的 manifest 自己要求管理员权限，会弹一次 UAC —— 点"是"。
   （XXMI Launcher 的 exe 要求管理员，非管理员启动会直接报 WinError 740，所以默认就按管理员处理。）

### 方式 B：从源码运行

```bat
pip install -r requirements.txt
run.vbs          :: 无控制台黑窗（推荐）
run.bat          :: 有依赖兜底与错误提示，但会闪一个 cmd 窗口
run.bat --cli    :: 不开界面，直接打印当前状态 JSON（调试用）
```

### ⚠ 数据根 = exe 所在目录

`config.json`、`runtime\`、`library\` 都生成在 **exe 所在目录**（源码运行时是仓库根目录）。
所以：**别把 exe 放进 `Program Files` 这类只读目录**，也别放在临时目录（清理工具会连你的 Mod 库一起删掉）。

### 首次启动会发生什么

1. **界面立刻出现**：窗口 1~3 秒内出现并显示加载页（从零启动实测 2.7 秒；窗口底色跟随主题，加载页至少显示 0.7 秒），**不存在"亮着窗口一片空白"的阶段**；全盘探测在首屏出来之后才开始，不挡界面；
2. 自动下载安装 XXMI / XXMI Libraries / EFMI；
3. XXMI 的配置是**它首次运行时自己生成**的，所以本程序会先拉起一次 XXMI 生成配置、随后关闭它，并在拉起 XXMI 之后提示：

   > 第一次启动可能失败 —— 建议再启动一次。
   > 点了 XXMI 里的 Start 之后，终末地有概率不会正常启动；如果发现游戏没开起来，**再启动一次**通常就好了。

   （提示只在"真的拉起来过 XXMI"或"还没走过首次引导"时出现一次，不会反复弹。）

4. 再点一次「一键启动」就会真正写好注入库并拉起 XXMI。

> **DLSS5 那套组件大部分没有上游可下载**（`renodx-endfield-enhancer.addon64`、`trans-zh.addon64`，以及 `renodx-dlss5` 的中文版，全网都没有自动可用的发布源），需要随包自备（`assets\dlss5\`）或从可用的旧环境复制到 `runtime\dlss5\`。缺了会明确提示缺哪个文件，而不是静默失败。
>
> **例外（2026-10-05）**：DLSS5 的**神经渲染运行库**现在有可用来源 —— 社区镜像
> [`RankFTW/rhi-repo`](https://github.com/RankFTW/rhi-repo) 按显卡架构分发（`official` / `sf` /
> `rtx40`，见「运行库按显卡架构自动切换」一节）。随包带 `official` + `sf` **两份**即可覆盖
> 全部受支持型号；40 系的 `rtx40` 优化版可在**依赖页**一键下载。从别处拿到的 zip（完整
> `assets-bundle.zip` 或单份组件 zip）也能用依赖页的「**导入随包 zip…**」直接导入 ——
> 那是**依赖组件**的入口（不是 Mod 包），导入前会**逐条校验**：manifest 要能解析、它列出的
> 每个文件的**全部分卷都得在包里**，缺一卷就拒绝并列出缺什么。

### DLSS5 装完直接玩，不需要手动配置

出帧所需的全部条件（ReShade shader 标准头与纹理、NGX 运行库、运动矢量来源、preset 里两个 technique 的启用与顺序）都由初始化自检自动写好、每轮校验，**不需要你进游戏点任何东西**：一键启动 → 进游戏 → 面板 `成功NR帧` 应该就开始涨。

想确认它真在工作，最直接是看 `runtime\dlss5\dlss5-feed.log`，成功时是这样：

```
################ feed: opening D3D12 session ################
[feed] NVSDK_NGX_D3D12_Init -> 0x00000001 (Success)
[feed] feature ready: 3840x2160 DLAA, flags=74 ...
[feed] frame 1 delivered (3840x2160, reset=1)
[feed] 600 frames: feed CPU 0.4x ms/frame ...
```

万一没出帧，按 FAQ「能进游戏但成功NR帧一直是 0」那三条路径排查（那里也包含"实在不行在面板里手工激活一次"的兜底做法）。

---

## 三、日常使用

### Mod 库页

- **导入**：把压缩包拖进窗口 → 出现全屏提示框 → 松手即导入（仅"Mod 库"页接受拖放；拖出窗口或按 Esc 会取消提示）。支持 **`.zip` / `.7z` / `.rar`**（0.7.2 及以前只支持 `.zip`）：`.zip` 走 Python 标准库；`.7z` / `.rar` 依次找 **项目内 `tools\7zip\7z.exe` → PATH 上的 7z → Windows 自带的 `System32\tar.exe`（bsdtar，libarchive 实现，能读 7z 与 rar）**，找不到解压器时会直说。加密包、缺分卷、坏包都会给出可读原因，且**不会在 `library\` 里留半成品目录**；解压出来一个 `.ini` 都没有时会提示"可能不是有效的服装 Mod 包"。
- **角色识别**：导入后按 Mod 名/ini 里的线索猜角色；**认不出就直接弹窗让你选**（不再只是提示你去点按钮），也可以稍后点卡片上的"角色待确认"。识别依据有三类写法：中文名（含常见误译与社区昵称，如「小羊」=艾尔黛拉、「杰哥」=洁尔佩塔）、官网英文代号（`estella` / `laevatain`…）、**中文拼音**（`zhuangfangyi` / `Zhuang_Fang-Yi` / `luoxi` / `alieshi` —— 下划线、连字符、空格、大小写都不影响）。
  **预识别**：当名字里同时出现多个角色名、分不清主次时（`庄方宜和伊冯的合集`），程序按"**和哪个角色相关字数最多**"先猜一个（3 字的「庄方宜」胜过 2 字的「伊冯」），把这个结果**预选**在弹窗下拉里 —— 但卡片上的黄字「角色待确认」照旧显示，**必须你点一下保存**才算数（猜错会让同角色互斥失效）。
  这张角色表**只认官网**（`endfield.hypergryph.com/operator`，一手来源；第三方聚合站的译名有硬错误）：程序每次启动后在后台跟官网对一次，上新干员时自动把新角色（含官网英文代号与美术 key）并进 `<数据根>\runtime\_state\characters.json`，**本地手工补的社区简称与拼音别名一律保留**（读取时随包表与运行时表的别名取**并集**，所以老用户的运行时表不会把拼音顶掉），也不会覆盖随包那份。想手工核对/更新就 `python scripts\fetch_characters.py`（`--write` 写运行时表，`--update-bundled` 才动随包表）；**发版前刷新过角色表后**再跑 `python scripts\gen_character_pinyin.py --write` 给新干员补拼音（拼音由 `pypinyin` 在**开发机**上生成并固化进 `characters.json`，运行时零依赖）。
  角色表是**随包资源**（构建脚本 `scripts\build_exe.py` 显式带着 `endfieldmodcontroller\characters.json`）—— 0.7.2 及以前的 exe 漏了它，发布版一直在用内置的 18 条兜底表；现在打包会带上 33 位 + 拼音。
- **每个 Mod 卡片右下角有「⋯」**：鼠标移上去就地弹出小菜单 —— **更换 Mod 归属…** / **修复（实验性）** / **回滚修复** / 打开所在文件夹 / **移出 Mod 库**（菜单顶部显示"归属：<角色> · 未修复过/可回滚"）。已修复过的卡片上会有「✓ 已修复过」标记。库页顶部还有「一键修复所有 Mod（实验性）」。
  「修复」用的社区工具（B站 up 主 可可HXL《终末地Mod修复工具包》v1.5）**没就位时这一项是置灰的**，鼠标悬停会告诉你该把 exe 放哪 —— 库页不再为此顶着一整段说明。
- **勾选**：勾选即保存（同角色自动互斥）。点「生成控制器」把选择落成 EFMI 要加载的内容。
- **你的 Mod 库是只读的**（用户 2026-10-01 定的硬规则）：程序**任何情况都不会**删除、移动或"整理" `library\` 里的东西 —— 重装组件、更新依赖、清理 staging、净化游戏目录都不会碰它。**唯一**会改动库的动作是你在卡片「⋯」里主动点「移出 Mod 库」（移到 `runtime\backups\mod-trash\`，可找回）。另外：**不要把「Staging Mods 目录」设成 Mod 库本身或它的上级/子目录** —— 清理 staging 是无条件删除，配错就等于删库；程序检测到这种重叠会**直接拒绝执行**并提示你怎么改。
- **强行关闭角色 Mod 互斥**（库页顶部拨钮，默认关）：便于**部分同角色但不冲突的 Mod**（例如一个改服装、一个只改贴图）。打开后，勾选一个 Mod 不会再把同角色的其它 Mod 自动取消，生成控制器时也不再按角色去重 —— 前端与后端两处一起放行。⚠️ 同角色的两个 Mod 同时生效**常常**会让游戏崩，只在确认它们改的不是同一批资源时再开；拨钮下方的说明栏会显示当前状态（关闭时列表上方那行提示会变成"同角色互斥已关闭"）。
- **热键（保留 Mod 原样，面板与其并存）**：Mod 作者在 readme 里写的快捷键、以及它自带的控制菜单（例如庄方宜那套按 **`ALT 0`** 打开）都直接生效。**「游戏内 Mod 面板」不会再锁这些键** —— 它**直接发这些原键**（见上文「面板的按键是怎么送进游戏的」），所以你手按和点面板效果相同、可以混用。`controller.ini` / `actions.tsv` 仍然照常生成：`actions.tsv` 是面板的动作清单；`controller.ini` 里那套内部键协议（`[KeyMC_*]`）**当前不生效、面板也不使用**（原因见上文那段弯路记录）。

### 启动页

- **一键启动**：补齐组件 → 同步 XXMI 注入库 → 初始化自检 → 拉起 XXMI（不自动进游戏；进游戏由 XXMI 或「启动游戏」按钮完成）。
- **打开官方 XXMI**：只打开 XXMI 自己的界面，不动注入库。
- **强制关闭**：收掉残留的 loader / 游戏进程（**不会**在你没要求的情况下强杀正在玩的游戏）。

### 设置页

路径配置（XXMI / 游戏 / loader / 乳摇工具）、下载加速与线路、主题、单实例与游戏多开防护、是否部署新版 nvngx、依赖清单等。
`config.json` 里的键与默认值可参考 `config.example.json`（由程序默认值直接导出）。

#### 用你自己已经装好的那份 XXMI（v0.6.1 起）

如果你原本就有一份装好 Mod 的 XXMI（例如 `F:\XXMI Launcher`），可以让本程序**只做编排、不再动它**：

1. 设置页「**XXMI Launcher**」填你那份的 `<你的 XXMI>\Resources\Bin\XXMI Launcher.exe`；
2. 设置页「**Staging Mods 目录**」填你那份的 `<你的 XXMI>\EFMI\Mods` —— Mod 是 stage 到这个目录的，指错就会"勾了 Mod 但游戏里没有"；
3. 关掉「**使用内置运行环境**」：关掉后程序不再下载/更新自带那份，也就不会再往这两个字段里写东西；
4. 保存设置 → 一键启动。

**行为保证**：这两个字段只要是你自己填的**外部路径**，安装/更新内置组件时**一律不会被改回去**；只有字段为空、或仍指向内置 `runtime/builtin/...` 时才会被自动填写。另外，当「XXMI Launcher」指向外部那份、而「Staging Mods 目录」还是内置默认值时，启动会自动把它跟到外部那份的 `EFMI\Mods`（避免 Mod 进错目录）。反向切回自带那份：打开「使用内置运行环境」、把这两个字段清空即可。

> **关于"部署新版 nvngx"**：默认**关闭**。DLSS5 的神经渲染接口（`NVSDK_NGX_D3D12_EvaluateFeature_C`）住在 `nvngx_dlssnr.dll` 里，本程序会把它放在 `runtime\dlss5\` 供 addon 加载；游戏目录里那份 `nvngx_dlss.dll` 保持**游戏原版**即可。打开这个开关会额外用新版覆盖游戏目录（改前留 `*.game_original`），**可能影响游戏启动**，不确定就别开。

### 公告与异常状态预警（发布入口）

管理器会**联网读**仓库根目录的 `alerts.json`（走 `api.github.com` —— 比 raw 域名在国内可达得多），用来发布两类信息。改这个文件 push 即生效，**不用发版**：

| level | 叫什么 | 行为 |
| --- | --- | --- |
| `info` / `warning` | **公告** | 管理器启动后弹一次，看完即记已读、下次不再弹。**不锁启动** —— 点掉就完事，不影响任何流程 |
| `critical` | **异常状态预警**（如大规模封号） | **每点一次「一键启动」都弹**（不记已读、没有开关），前端**强制停留** `hold_seconds` 秒（倒计时期间按钮不可点），并且必须三选一：**还原配置**（右侧橙色主选项、默认聚焦）/ 保持配置但不启动 / 仍然启动 |

字段：`id`（必填且唯一，用来记已读）、`title`、`body`（支持换行）、`url`（可选，详情链接）、`hold_seconds`（可选，覆盖顶层 `default_hold_seconds`；默认 10、上限 120）、`until`（可选 `YYYY-MM-DD`，过期后自动不再提示）、`min_version` / `max_version`（可选，**版本区间**，见下）。

**版本区间（专门用来避免公告越积越多）**：管理器拉到条目后会拿**自己的版本号**去比对，不在区间内的条目**直接不弹** —— `critical` 异常状态预警**同样受这个限制**（公告与防护机制共用同一套判据）：

| 写法 | 谁能收到 |
| --- | --- |
| `min_version` 与 `max_version` **都留空** | **所有版本都能收到** —— 重大信息、安全预警走这条 |
| 两个都填**同一个版本号**（如都填 `0.9.4`） | **只有装了那个版本的人**看得到 —— "这个版本发的公告"，最常用 |
| 只填 `min_version` | 从那一版起（含）的所有版本 |
| 只填 `max_version` | 到那一版为止（含） |

> 读不出本地版本时**不拦**（宁可多提示一次，也别漏掉安全预警）。

**「还原配置」具体做了什么**（都能撤销）：① 关掉全部注入开关（DLSS5 / 服装 Mod / 乳摇 / 摆姿）并按新开关重写 XXMI 注入库；② 走游戏目录净化，把第三方文件**先备份再移走** —— 也就是回到"纯原版可启动"的最安全状态。还原前的开关快照写在 `runtime\_state\alert_restore_point.json`；撤销接口 `undo_alert_safe_mode` 会把开关恢复原状，游戏目录文件用设置页「一键还原游戏本体」搬回。

落地文件都在 `runtime\_state\`：`alerts_cache.json`（上次成功拉到的那份，断网时回退用它）、`alerts_seen.json`（已读公告 id）、`alert_restore_point.json`（还原点）。**拉取失败一律静默**，不影响启动、更不拖慢首屏。

> **正式版只从仓库读这份文件**（没有"读本地文件覆盖"的通道）—— 预警是保护通道，不能留下"放个文件就能把它挡掉"的口子。

### 游戏目录净化 / 还原

把游戏目录里的第三方注入物（loader proxy、插件数据、残留 ReShade 痕迹）**先备份再移走**，备份在 `runtime\game_backup\<时间戳>\`（含 `manifest.json` 与还原所需的文件），随时可还原。
净化前会做内容级判定：**内容不像 ReShade/loader 载荷的 DLL 不会被误移走**（例如游戏自带或他方放的正版 `d3d12.dll`）。

### Endfield Poser（摆姿 / MMD 播放，可选）

启动页第 5 个滑块就是它。装什么、怎么装都由**它自己的安装向导**决定，本程序只做三件事：

1. **下载**：从它的官方 Release 取 `Endfield-Poser-v<版本>-win64.zip`（约 6.9 MB，Release 自带 sha256 校验），解压到 `runtime\poser\`；
2. **安装**：调它包内的 `tools\deploy.ps1 -GameDir <游戏目录> -Action Install`，由向导把 `plugin\poser.dll` 与 `d3dcompiler_47.dll`（proxy）写进游戏目录，并复制 37 份角色表情校准。**本程序不直接写这两个文件** —— 向导自带校验、原子写、失败回滚与安装记录（`plugin\poser-install.json`）；
3. **开关**：关掉只把 `plugin\poser.dll` 改名为 `plugin\poser.dll.endfieldmodcontroller.disabled`（loader 只扫 `*.dll`，所以立刻不生效），**不动 proxy、不动其它插件**；要真正移除文件请用「卸载」（走向导的 Uninstall）。

游戏内：按 **L** 开面板、**P** 冻结/解冻、按住 **Alt** 取光标、`Ctrl+F5/F6/F7/F8` 播放/暂停/停止/回首帧。它还有一个独立摆姿页 `http://127.0.0.1:18923`（游戏运行时用浏览器打开；启动页有「打开摆姿页（Poser）」按钮，设置页「启动与诊断」里有「打开 Poser 日志」可直接看 `plugin\poser_log.txt`）。首次进游戏需要在游戏内确认它的《用户协议》，未确认前那个页面只给只读状态。

**它和乳摇（SecondaryMotion）能共存**，因为两者用的是同一套注入机制：游戏目录里的 `d3dcompiler_47.dll` proxy 会把 `plugin\` 下所有 `*.dll` 加载进游戏进程。因此卸载其中一方时，只要另一方还在，proxy 会被保留（上游向导与我们自己的乳摇卸载逻辑都是这么做的）。

> 上游是 **AGPL-3.0**，本程序**不随包分发**它的二进制，只从官方 Release 下载并调用它自己的安装向导；使用前请确认其协议与鹰角官方创作限制。

---

## 四、目录结构

```text
<exe 所在目录>/
├─ config.json                  运行配置（原子写；损坏会被隔离成 config.json.broken-<时间戳>）
├─ library/                     Mod 库（你拖进来的 zip 解压到这里）
└─ runtime/
   ├─ builtin/XXMI/             自动下载安装的 XXMI Launcher + Libraries + EFMI
   ├─ dlss5/                    DLSS5 底座与插件（d3d12.dll / ReShade.ini / ReShadePreset.ini
   │                            / *.addon64 / nvngx_*.dll / reshade-shaders / dlss5-feed.cfg）
   ├─ reshade/                  控制器自己的 addon 与 actions.tsv
   ├─ secondary_motion/         乳摇工具（可选）
   ├─ poser/                    Endfield Poser 安装包（从官方 Release 下载，不随包分发）
   ├─ game_backup/<时间戳>/      游戏目录净化备份（可还原）
   ├─ backups/                  引擎目录、配置等的历史备份
   ├─ logs/                     日志与诊断包（logs/bundles/*.zip 是崩溃包）
   └─ _update/                  自更新下载与残留
```

`library/` 是**你的数据**，任何自动清理都不会碰它；相反，控制器自己的产物一律带 `MC_` 前缀，便于区分。

---

## 五、常见问题

### DLSS5 相关（面板显示不正常时按顺序看）

**Q：面板显示「0 渲染」/ `NGX Hook 创建 0`？**
`nvngx_dlssnr.dll` 没就位。确认 `runtime\dlss5\` 里有这两个文件：`nvngx_dlss.dll`（58,977,904 B）与 `nvngx_dlssnr.dll`（165,840,496 B）——**游戏目录保持原版即可**，不需要动它。日志里会有 `Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C` 这条（正常，它旁边的 `EvaluateFeature hooked` 才是关键）。

**Q：能进游戏，但「成功NR帧」一直是 0？**
正常情况下不该出现——初始化自检会把下面三件事都办好。真遇到了按顺序查：
1. `runtime\dlss5\dlss5-feed.log` 里是不是 `motion vectors will be zero (still images only)` —— 是的话说明运动矢量来源没配，`ReShade.ini` 的 `[GENERAL] PreprocessorDefinitions` 与 `ReShadePreset.ini` 里都要有 `DLSS5_MV_PROVIDER=1`（重跑一次「一键检测全部」会补）；
2. 日志里是不是 `Failed to compile ... DLSS5_Feed.fx: could not open included file 'ReShade.fxh'` —— 是的话说明缺 ReShade 标准头，重跑自检（`dlss5:shader_deps` 会补齐；注意 `runtime\dlss5\reshade-shaders\Textures\` 也要有文件，空目录同样不行）；
3. 日志里是不是 `LaunchPad technique found (DISABLED)`、或者只有 `LaunchPad technique found (enabled)` 却没有 `opening D3D12 session` —— 说明 preset 里的 technique 没有真正生效。先确认 `ReShadePreset.ini` 里 `Techniques=` 含 `MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx` 与 `DLSS5_Feed@DLSS5_Feed.fx`、`EffectSorting=MartysMods_LAUNCHPAD.fx,DLSS5_Feed.fx`；**必须完全退出游戏后再改**（`AutoSavePreset=1` 时 ReShade 退出会把内存状态写回、覆盖你的改动）。若仍不生效，兜底手段是进游戏按 Home → 主页 → 效果列表，把 `iMMERSE: Launchpad` 与 `DLSS5_Feed` 各点一次「置顶激活效果」（并保证 Launchpad 排在 DLSS5_Feed 之上），正常退出让 ReShade 自己写回 preset。

**Q：ReShade 提示「编译一些效果时出现了错误」？**
那是完整 shader 集合里几个无关效果（`MartysMods_FFTBLOOM.fx`、`INSIGHT.fx`、`RSRetroArch\mdapt.fx`、`DH\dh_uber_rt.fx`、`AstrayFX\RadiantGI.fx`）编译失败，**与 DLSS5 无关**，程序会把它们移到 `_quarantine_bad_shaders\`。真正要关心的是日志里有没有 `Failed to compile ... DLSS5_Feed.fx: could not open included file 'ReShade.fxh'` —— 那说明缺 ReShade 标准头，重跑一次自检即可（`dlss5:shader_deps` 会补齐）。

**Q：`dlss5-feed.addon64` 该用哪一版？**
**两版都能用，不必刻意回退。** 程序随包分发的是 0.1.0（76,800 B），而「一键安装/更新全部组件」会把它更新成上游最新版；2026-09-30 实测：**1.18.0-beta.1（332,800 B）在终末地上正常出帧**（`dlss5-feed.log` 从 13:19 到 13:22 一路到第 7200 帧、35 fps、NGX 310.8，那次游戏是正常退出）。判断它有没有工作**别只看版本号**，看两处：`runtime\dlss5\dlss5-feed.log` 里有没有 `opening D3D12 session` → `frame N delivered`，以及游戏内面板的「成功NR帧」是否在涨。（此前 README 写过"1.18 不会出帧"，2026-09-30 已按实测更正。）

### 崩溃与自检（0.6.0 起）

**Q：崩溃弹窗说「这次崩溃很可能由 Mod 资源冲突引起」，怎么办？**
自检在启动时发现你的 `Mods` 里有 Mod 覆盖了同一批资源（最常见是两个 Mod 改了同一个角色的同一批贴图/模型），它们同时生效会让游戏在**加载过程中**闪退。按弹窗里的按钮直接去「Mod 库」页，把冲突的两个里取消勾选一个 → 点「生成控制器」→ 再进游戏。这一步比先怀疑注入更容易验证。清理后还崩，再把诊断包发到 issue 或 QQ 群 —— 那时弹窗会回到普通的「检测到终末地异常退出」。

**Q：自检报「随包组件与基线不一致」？**
说明 `runtime\dlss5\` 里的组件和本程序随包的那一版**对不上**（多半是拿别的「DLSS5 整合包」覆盖过，或者文件被改坏 / 解压不全）。分两种处理：

- **随包组件**（ReShade 底座、两个 nvngx 运行库、几个 addon）：**程序会自动按基线重新展开**，你不用管 —— 你原来那份会备份成 `<文件名>.bak-before-baseline-restore`，想还原随时改回来。这类损坏很隐蔽：文件看着都在，表现却是**游戏每次启动几十秒后崩在显卡着色器编译器**（`nvgpucomp64`）。
- **在线组件**（`dlss5-feed.addon64`）：**不会被自动改回去** —— 它本来就允许换成上游最新版。随包 0.1.0（76,800 B）与上游 1.18.0-beta.1（332,800 B）**都属已知可用**，自检不报警；落在已知版本之外才会提示。真觉得 DLSS5 没生效时，看 `runtime\dlss5\dlss5-feed.log` 与面板「成功NR帧」。

**Q：点「一键启动」时弹出「启动前发现 Mod 冲突风险」？**
这是在**拉起 XXMI 之前**拦的一道确认，判据有两类（都是算好的事实，不是猜）：
- **资源冲突**：自检发现两个 Mod 覆盖同一批游戏资源（典型是同一角色的两个服装 Mod）；
- **崩溃记忆**：这套 Mod 组合（**或它的一部分**）以前真的崩过 —— 程序会把每次崩溃时跑的是哪套 Mod 记在 `runtime\_state\crash_memory.json`，下次勾到相同/相近组合就提醒。

点「**先去清理，不启动**」（弹窗里**右侧的橙色主选项**，默认就聚焦在它上面，直接按 Enter 也是它）会直接把你带到「Mod 库」页（取消勾选冲突项 → 「生成控制器」）；点左侧的「仍然启动」才照常继续，但游戏有可能在加载过程中闪退。清理完再启动就不会再提示。（正常退出**不会**进崩溃记忆，不会因此打扰你。）

**Q：崩溃包 / 诊断包里都有什么？**
控制器日志、终末地自己的日志（`Player.log` 与崩溃转储目录）、注入快照、Windows 事件、**DLSS5 现场**（`dlss5-feed.log` / `ReShade.ini` / `dlss5-feed.cfg`），以及 `cause.json`（这次退出的归因：Mod 冲突 / 其它崩溃 / 正常退出）。报告正文里也有一行「归因 : …」。
（发之前记得**附上现象**；发到哪见这一节最后那条 Q&A —— GitHub issue 或 QQ 群都行。）
`summary.txt` 里另有几段**判据**：`-- DLSS5 运行库指纹 --`（两个 nvngx 运行库的精确字节与基线 sha256）、`-- XXMI 注入链摘要 --`（`active_importer` / `extra_libraries` 每条文件在不在 / 签名长度）、`-- DLSS5 shader 文件清单 --`（关键 .fx 的字节数与 preset 的 `Techniques=` 行）、`-- 运行时组件清单（runtime\dlss5）--`（**每个文件的字节数 + sha256 前 16 位 + 是否偏离随包基线**，同样内容另存一份 `runtime-inventory.txt`）；**另外还有一段 `-- 设备与显卡 --`**（CPU、内存、系统版本、每块显卡的名称 + 驱动版本 + 显存，以及一句「DLSS5 前提」判断）—— 用来一眼分清"他的机器是不是根本不支持"（没有 N 卡 / GTX 老卡）和"我们这边配错了"。

**Q：某个文件老是被删掉、补上又缺，怎么办？**
多半是**安全软件把它当威胁隔离了**（最常见的是 `runtime\dlss5\nvngx_dlssnr.dll` 这种 165 MB 的大文件，以及几个 `*.addon64`；注意安全软件也可能只是"删除"而不是移入隔离区，从隔离区恢复没用）。
程序**每次启动控制器时会给关键文件拍一次"在不在"的快照**（记在 `runtime\_state\file_watch.json`），判定条件是三条同时成立：
1. 这个文件**曾经就位过**（从没装过 = 还没下载，不算）；
2. **连续两次启动**都发现它不在；
3. **同组还有别的文件在**（安全软件删的是**单个文件**；你自己清理/改名备份是**一整片**都没了 —— 这条用来避免冤枉杀毒软件）。

**弹窗时机**：挂在**「一键启动」**上 —— 点了一键启动之后、在自检**补齐这些文件之前**弹出（那时"补了又被删"的现场最清楚）；**打开管理器时不弹**，只在日志里留一行 `文件守护: …`。弹窗列出具体文件与"已缺几次"，并给出**建议加入白名单的目录**（右侧橙色主按钮「打开目录加白名单」直接就打开了）。看过并处理过之后不再重复弹（记在同一个 json 里）。（把文件改名成 `.disabled-by-mc`、或挪进 `_disabled\` 目录**算"主动停用"**，不会被误判成被删。）

**Q：点「修复」和点「一键启动」有什么区别？（0.7.2 起）**
一样能自愈。以前「修复」只做"装组件 + 重新生成控制器 + 写注入库"，**不做**「一键启动」链路里的两件事：① XXMI 的配置文件是它首次运行时才生成的，配置不存在时先替你拉起来生成一次；② 补齐随包资产（`assets`，含 DLSS5 的 shader 与 `ReShade.ini`）。所以那时候**配置缺失或资产包没下下来，点多少次「修复」都只会重复报同一句缺失**。现在两条链路完全一致；修复过程中会自动打开日志窗，能看到每一步（含下载进度）。

### 其他

**Q：乳摇管理器每次都要我选游戏文件夹？**
`<乳摇工具目录>\SecondaryMotion\settings.json` 里的 `game_data_dir` 必须是 **`<游戏目录>\SecondaryMotion`**（数据目录，不是游戏根目录）。程序初始化时会自动写好；要手动改的话注意这一点。

**Q：第一人称没效果，点面板按钮也没反应？**
`runtime\dlss5\ReShade.ini` 的 `[endfield-enhancer]` 段里，`CameraEFMICompatibility` 必须是 `1`（与 EFMI 服装 Mod 共存所必需），另外 `CameraFirstPersonMovement` / `CameraMeshHeadHiding` / `CameraFirstPersonDialogue` / `CameraSmoothPerspectiveTransition` 都建议为 `1`，`ShortcutFirstPerson=112`（F1）是切换键。程序初始化时会写入这套可用默认值。

**Q：点了一键启动，Mod 没生效 / 注入失败？**
看启动页的初始化自检结果与 `runtime\logs\launch.log`。常见原因：XXMI 配置还没生成（第一次要点两次启动）、注入库被 XXMI 自己的设置弹窗重置、`d3dx.ini` 的 `[Loader] target` 指错、或游戏目录残留了旧的 loader proxy（用"净化游戏目录"处理）。

**Q：游戏起不来 / 进游戏闪退？**
先看 `runtime\logs\bundles\` 里最新的崩溃包（程序检测到异常退出会自动打包，里面含游戏的 `Player.log`、CrashSight 日志、模块列表与我们的分析）。已排除过的常见原因：注入库同时挂了两个 ReShade 底座、mod 之间同角色冲突、游戏目录缺 `d3dcompiler_47.dll` / `vulkan-1.dll`。**也不要同时开"部署新版 nvngx"**。

**Q：第一次启动会很慢吗？**
不会。窗口 1~3 秒内出现（从零启动实测 2.7 秒），而且**任何阶段都不会出现空白窗口**：窗口底色跟随主题、加载页至少显示 0.7 秒，并分步提示「正在绑定界面 → 正在读取配置 → 正在扫描 Mod 库」。
费时间的是后台"遍历盘符找 XXMI / 3DMigoto / 乳摇工具"，它在首屏出来**之后**才开始，只影响设置页那几个「检测到的路径」字段（探测完自动补上），不影响你操作。真正看网速的是首次下载安装 XXMI / Libraries / EFMI。

**Q：下载慢 / 连不上 GitHub？**
设置页把"下载加速"设为自动、线路设为自动即可：平时单连接，慢或断流时临时并发分块并临时切镜像线路；**镜像下载物会用 Release 提供的 sha256 校验**，校验不过就丢弃重来。用完线程池即销毁，不常驻、不改 hosts、不装证书。

**Q：反作弊会不会有问题？**
本程序不注入、不碰反作弊；注入由 XXMI/EFMI 完成，且只作用于游戏目录里那几个已知文件。所有对游戏目录的改动都可备份、可还原。风险自负（见免责声明）。

**Q：崩溃了 / 出问题了怎么反馈？**
程序检测到游戏异常退出时会自动把「控制器日志 + 游戏日志 + 崩溃转储」打包到 `runtime\logs\bundles\crash-<时间戳>.zip`，在弹窗里点「打开路径」即可定位。平时也可以随时点**设置页最上方的「一键导出诊断包」**（或日志窗里的「导出诊断包」）—— 导出后会弹出「怎么反馈」的窗口。

两条路都行：**GitHub issue**（把 zip 拖进正文）或 **QQ 群 `1045239747`**（加群验证答案 `jing_hy`）。**两种方式都请附上现象**：什么时候出现的、你点了什么、屏幕上看到什么（报错原文或截图）—— 诊断包里没有"你做了什么"这一层。

---

## 六、开发

```bat
pip install -r requirements.txt
python -m pytest tests -q        :: ← 必须指定 tests 目录（见下）
python scripts/self_check.py     :: 跑测试 + 检查 dist 里的 exe / addon / --cli
python scripts/build_exe.py      :: 打包单文件 exe → dist\EndfieldModController.exe
python -m endfieldmodcontroller --cli   :: 打印状态 JSON
```

> ⚠ 不要直接在仓库根跑 `python -m pytest -q`：那会把 `_tmp\` 下的临时脚本一起收集，和 `tests\` 里的模块重名后直接报 collection error（整套要跑几分钟才中断）。**用 `python -m pytest tests -q`**（约 7 秒）。

主要模块：

| 模块 | 职责 |
| --- | --- |
| `config.py` | 配置读写（原子写/损坏隔离）、路径解析、内嵌组件探测（带缓存与"深/浅"两档） |
| `core.py` | Mod 库扫描、角色识别、ini 解析与热键改写（`patch_mod_hotkeys`，**默认不启用**，见「热键」那条）、控制器产物生成、`d3dx_user.ini` 读写 |
| `activation.py` | 选择解析（同角色互斥/依赖按需）、staging 生成与清理 |
| `launcher.py` | 一键启动、注入库维护、XXMI 配置读写、ReShade 运行时准备、进程收尾 |
| `api.py` | 暴露给前端的接口层（pywebview `js_api`）；构造必须保持"快"，重活放后台预热 |
| `initialize.py` | 初始化自检（ReShade.ini 重建并**保留所有段**、DLSS5 shader/preset/运动矢量、游戏目录运行库、Mod 冲突检测） |
| `secondary_motion.py` | 乳摇：状态、注入、模板实例化、`settings.json`（游戏数据目录） |
| `sbm_data_sync.py` | 乳摇**角色参数**：后台从仓库拉取并**只补本地缺失的角色**（来源可用 `sbm_data_source` 指向自己的 fork；绝不碰 `presets\User.json`） |
| `poser.py` | Endfield Poser（摆姿 / MMD）：状态、安装包下载、调**它自己的**安装向导、开关（重命名 dll）、只读读它的摆姿页 |
| `dependencies.py` / `runtime_deps.py` | 依赖清单、下载与解压（逐文件原子替换）、XXMI/Libs/EFMI 安装 |
| `dlss5_fetcher.py` / `reshade_integration.py` | DLSS5 组件、ReShade 集成与游戏目录注入审计 |
| `game_clean.py` | 游戏目录净化/还原（备份式、内容级判定、越界拒绝） |
| `fastnet.py` / `github.py` / `fsutil.py` | 下载（并发/镜像/校验）、GitHub 查询与缓存、哈希与原子写公共件 |
| `diagnostics.py` / `crashwatch.py` | 日志、诊断包、崩溃监视与报告 |
| `deviceinfo.py` | 设备与显卡型号（只读注册表 + ctypes，**不起子进程**）：写进诊断包/崩溃包，用来判断"是不是显卡不支持" |
| `filewatch.py` | 文件守护：每次启动给关键文件拍一次"在不在"，**曾经在 + 连续两次启动都缺 + 同组还有别的文件** → 弹窗提醒加入杀软白名单 |
| `web/` | 前端（原生 HTML/CSS/JS，pywebview 里跑） |

### 测试清单

仓库根目录的 `TESTING.md` 是一份可照做的全功能验收清单（按测试环境分段、编号稳定，出问题按编号反馈即可）。

---

## 七、发布规则

四个固化脚本（**构建**与**推送/上传**分开；推送与上传永远由你自己执行）：

```bat
python scripts\build_release.py          :: 静态检查 → 构建最新版 + 带版本号副本 + 伪旧版 → 归置旧版
python scripts\push.py                   :: **先自动做状态快照**，再推 main（只推代码，不发 Release）
python scripts\prepare_release.py        :: 校验产物 + 生成 assets-bundle.zip + 打印上传指引
python scripts\upload_release_assets.py  :: 上传两个附件（大文件走直连，见下）
```

> **推送前必须快照（2026-10-01 起，用户要求「每次推 github 都要做快照」）**：
> `scripts\push.py` 会先跑 `scripts\snapshot.py` 把"此刻到底是什么环境"整份记下来 ——
> `git` 状态、exe/addon 的 sha256、数据根（modtest）的关键文件、游戏目录的完整清单、以及
> 哪些开关开着/勾了哪些 Mod。**快照失败就不推**（`--skip-snapshot` 可显式跳过，不推荐）。
> 快照落在**工作区上级**的 `_snapshot_<版本>-<时间戳>\`（不进仓库、不污染 `git status`），
> 只复制 2 MB 以内的小文件、大文件只记 sha256，`--keep`（默认 10）自动清理更旧的。
> **为什么要这么做**：当天排查一个 bug 时环境被改了多处，之后每一次「还是不行」都不再是
> 同一条件下的复现 —— 有了快照才能回到"那一版当时到底是什么状态"。
> `build_release.py --snapshot` 也可以在构建后手动留一份（快照失败不影响产物）。

> **大文件上传的坑（实测）**：机器上开着 Steam++ / Watt Toolkit 时，它会把 github
> 相关域名写进 hosts 指向 `127.0.0.1` 的本地反代，而该反代对**大 body 的 POST 上传**支持不好 ——
> 实测 1 / 5 / 20 / 60 MB 都能过，126 MB 的 `assets-bundle.zip` 会在发出约 100 KB 后被强断
> （`gh release upload` 报 HTTP 502：`RequestBodyDestination … 远程主机强迫关闭了一个现有的连接`）。
> `upload_release_assets.py` 的做法是：用 DoH 查真实 IP，再用 `curl --resolve` 直连上传
> （实测 126 MB / 23 秒 / 5.7 MB/s 成功），**不改 hosts、不动系统代理**，下载路径不受影响。

`build_release.py` 的静态检查（任一失败即中止，**不会**产出半成品）：所有模块 `py_compile`、
`node --check web/app.js`、`python -m pytest tests -q`。

本地产出**三份 exe**，旧版自动归置：

| 产物 | 用途 | 是否上传 |
| --- | --- | --- |
| `dist\EndfieldModController.exe` | 最新版，唯一发行的 exe | ✅ 上传 |
| `dist\EndfieldModController-<版本>.exe` | 带版本号副本（留档） | ❌ 不上传 |
| `EndfieldModController-0.1.9-from-<版本>.exe`（`dist\` 与仓库根各一份） | 伪旧版，用于测试自更新 | ❌ 不上传 |
| `dist\_old\` | 上一代及更早的带版本号副本（构建时**自动归置**；旧伪旧版直接删除） | — |

- 「只上传不带版本号的那个」这条规则**只约束 exe**；其它附件照常上传。
- `dist\` **只留构建产物**：构建脚本会自动清掉 exe 在 dist 里跑过留下的 `config.json` / `runtime\` /
  `library\`，以及早期 `--onedir` 的残留目录（`dist\EndfieldModController\`）。
- Release 附件 = **`EndfieldModController.exe` + `assets-bundle.zip`** 两个。
  单文件 exe 装不下运行时资产（`assets/nvngx` 本身是 xz 分卷），程序在本地找不到
  `assets\` 时会自动从 Release 下载这个包并展开 —— `prepare_release.py` 会调用
  `scripts\build_assets_bundle.py` 现打一份 `dist\assets-bundle.zip`（+ `.sha256`）。
  ⚠️ **改过 `assets\` 之后一定要重新生成它**，别拿旧包发布。
- **不做便携版**（没有 portable zip，也没有相应的打包脚本）。
- 版本号：**只跟"最新 Release"比** —— 本地保持在「最新 Release + 1」；GitHub 上**只推了源码
  （main 更新）但没发 Release 时，版本号不用改**（推送发版之后才轮到下一个号）。
  `scripts\release_version.py` 把这条规则做成了可执行的核对，`build_release.py` 与
  `prepare_release.py` 各跑一遍（查不到最新 Release 时只提示、不阻断）。
- 伪旧版的版本号固定写成 `0.1.9`（代码是最新的），命名刻意取"旧版本号"以便一眼分辨；
  上一代伪旧版在下次构建时**自动删除**。

---

## 八、第三方组件与许可

| 组件 | 用途 | 许可 |
| --- | --- | --- |
| [XXMI Launcher](https://github.com/SpectrumQT/XXMI-Launcher) | 注入器与启动器 | MIT |
| [XXMI-Libs-Package](https://github.com/SpectrumQT/XXMI-Libs-Package) / [EFMI-Package](https://github.com/SpectrumQT/EFMI-Package) | 注入库与服装 Mod 引擎 | MIT |
| [3DMigoto](https://github.com/bo3b/3Dmigoto) | EFMI 的底座 | MIT |
| [ReShade](https://reshade.me/) | 后处理底座（Addon 版） | BSD-3 |
| [RenoDX DLSS](https://github.com/clshortfuse/renodx) | DLSS5 神经渲染 | MIT |
| Endfield Enhancer（RenoDX 出品） | 第一人称 / 相机（英文原版） | MIT |
| **第一人称中文补丁** —— B站 up 主 **Hirahido** | 第一人称 / 相机面板的**中文**版本 | 版权归原作者 |
| [iMMERSE](https://github.com/martymcmodding/iMMERSE)（Marty's Mods） | ReShade 后处理链（Launchpad 等） | MIT |
| DLSS 5 Feed（`dlss5-feed.addon64`） | 给 DLSS5 喂颜色/运动矢量/深度 | 见其说明（无公开仓库，随包分发） |
| [ShakingBreastManager / SecondaryMotion](https://github.com/Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics) | 乳摇 | 见上游仓库 |
| [Endfield Poser](https://github.com/OedoSoldier/Endfield-Poser)（`honxi1/Endfield-Poser` 的功能分支） | 摆姿 / MMD 播放（可选） | **AGPL-3.0** —— **不随包分发**，只从它的官方 Release 下载并调用它自己的安装向导 |
| **Endfield PS-T DrawSection Fix v2.1**（《终末地Mod修复工具包》v1.5）—— **B站 up 主 可可HXL** | Mod 卡片的「修复（实验性）」与「一键修复所有」 | 版权归原作者（B站搜索「可可HXL」可找到工具包与教程）；**随包分发**，使用方式按其教程：在**临时目录**里跑，不把 `_ps_t_draw_fix_backup_*` 与日志留在 Mods 里 |
| NVIDIA NGX 运行库（`nvngx_dlss.dll` / `nvngx_dlssnr.dll`） | DLSS 与神经渲染运行库 | NVIDIA 版权，随包仅为免去手动下载 |
| **社区 DLSS NR 运行库变体**（`nvngx_dlssnr.sf.dll` / 依赖页的 `rtx40`） | 让 **RTX 20 / 30 / 40 系**也能跑 DLSS5 神经渲染（内核重定向到 sm_75/86/89） | 取自社区镜像 [RankFTW/rhi-repo](https://github.com/RankFTW/rhi-repo)（`dlssnr-310.8.SF-v2` / `dlssnr-310.8.0-RTX40`）；NVIDIA 运行库本身**闭源、无公开许可**，此处按其发布分发。若权利人有异议，在 issue 里说明即移除 |

**关于第一人称中文补丁（特别声明）**：随包分发的第一人称**中文**补丁由 **B站 up 主 Hirahido** 制作，
版权归其所有（源自作者发布的"终末地EE"）。
本程序**只做分发与安装编排**，不修改其内容；如果你是该补丁的作者且不希望被随包分发，
请在 issue 里说明，我会立即移除。英文原版第一人称插件来自 **Endfield Enhancer**（RenoDX 出品，无公开仓库，同样随包分发）。

各组件版权归原作者所有。本程序只做编排、自检与备份还原，不修改这些组件的源码。

---

## 九、免责声明

- 本程序**不是**官方工具，与鹰角网络 / Hypergryph 无关。
- 使用 Mod 可能违反游戏用户协议，**风险由使用者自负**；请自行确认你所在环境的规则。
- 本程序会读写游戏目录中的注入类文件（`d3d12.dll` / `d3dcompiler_47.dll` / `vulkan-1.dll` / `plugin\sbm.dll` / `plugin\poser.dll` / `plugin\poses\` / `plugin\mmd\` / `SecondaryMotion\` 等），但一律先备份、且提供一键还原；**不会**修改游戏本体、资源与存档。
- 第三方组件由其原作者维护，出问题请先到对应仓库反馈；本程序的集成问题欢迎开 issue，或加 **QQ 群 `1045239747`**（验证答案 `jing_hy`）。


## 前端技术栈与构建

界面在 **1.0.0** 换代：从"原生 HTML/CSS/JS"迁到 **Vue 3 + Vite + Tailwind CSS**。

* 源码在 `frontend/`（`src/pages/*.vue` 一页一个文件、`src/components/ui/*` 是共用组件、
  `src/lib/bridge.js` 是**唯一**的 pywebview 桥接点、`src/lib/settings.js` 集中所有设置项）。
* 构建：`cd frontend && npm install && npm run build` —— 产物是**单文件** `web/dist/index.html`
  （JS/CSS 全内联，并强制打成 IIFE，这样 pywebview 继续用 `file://` 加载，**不需要起本地 HTTP 服务**）。
* **切换开关**：`web/dist/.ready` 标记文件。有它 → 程序加载 `web/dist/index.html`（新前端）；
  没有 → 回退 `web/index.html`（旧前端）。打包脚本与 `app.py` 都按同一个判据走，
  所以"前端没构建好"永远不会打出坏包。
* `scripts/build_release.py` 会校验**产物不比 `frontend/src` 旧**（防止改了源码忘了构建）。
* 设计令牌在 `frontend/src/styles/tokens.css`：浅色基底 + 去饱和强调色；6 套主题沿用原名字
  （`light/dark/amber/cyan/violet/emerald`，存在 `localStorage('mc-theme')`，改名会让用户设置失效）。
* ⚠️ **日志框在任何主题下都是纯黑 + 可复制**，这是硬要求，换皮时不能丢。
