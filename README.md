# EndfieldModController

《明日方舟：终末地》的一站式 Mod 管理器：把 **DLSS5 神经渲染 + 第一人称视角 + 服装 Mod（EFMI）+ 乳摇物理 + 摆姿 / MMD 播放**统一到一次「一键启动」里；运行环境从零自动装好，**零配置启动即用**。

Windows 桌面程序（Python + Pywebview），单文件 exe。当前版本 **0.6.0** —— [下载最新版](https://github.com/jing-hy/EndfieldModController/releases) · [本版更新内容](https://github.com/jing-hy/EndfieldModController/releases/tag/v0.6.0)

> 📖 **这里是简略版**（写给正常使用的你）。
> 安装细节、目录结构、逐项故障排查、开发与发布流程 → **[详细文档](docs/README.detailed.md)**

---

## 它是怎么工作的

本程序**只做编排与自检**，不重写任何别人的东西：

```text
   一次「一键启动」做了什么
   ┌──────────────────────────────────────────────────────┐
   │ ① 检查并补齐运行环境（缺哪个装哪个，带校验）         │
   │ ② 维护 XXMI 的「注入库」——它决定哪些 DLL 进游戏     │
   │ ③ 跑一遍初始化自检（不对就修，修不了就明确告诉你）   │
   │ ④ 拉起 XXMI Launcher，你在它的界面点 Start 进游戏    │
   └──────────────────────────────────────────────────────┘

   游戏进程里同时存在的东西（全部由上面的注入库决定）
   ┌──────────────────────────────────────────────────────┐
   │  一个 ReShade 底座                                   │
   │    ├─ DLSS5 神经渲染                                 │
   │    ├─ 第一人称 / 相机                                │
   │    ├─ 面板汉化、喂帧组件                             │
   │    └─ 后处理 shader                                  │
   │  服装 Mod 引擎（EFMI）                               │
   │  乳摇注入代理                                        │
   │  摆姿 / MMD 注入代理（可选）                         │
   └──────────────────────────────────────────────────────┘
```

三条关键设计：

1. **一个游戏进程只能有一个 ReShade 底座** —— 所以程序把 DLSS5 与第一人称合到同一个底座上，不会给你塞两份；这也是"两个整合包混着用必崩"的原因。
2. **它不改游戏本体** —— 写进游戏目录的都是注入类文件，且**改动前一律先备份、随时一键还原**；游戏本体、资源、存档一律不碰。
3. **它不内置 Mod** —— Mod 都是你自己放进去的；程序负责解压、识别角色、同角色互斥，以及在启动前把"可能崩的组合"拦下来。

## 它能做什么

| | |
| --- | --- |
| **从零装好环境** | 首次启动自动下载安装 XXMI / XXMI Libraries / EFMI，装完写好配置 |
| **Mod 库** | 把 `.zip` 拖进窗口即导入；自动解压 + 识别角色，拿不准会问你 |
| **同角色互斥** | 同一个角色只保留一个 Mod（同时加载两个同角色 Mod 会崩） |
| **一键启动** | 维护注入库、补齐组件、跑完整自检，然后拉起 XXMI |
| **插件开关** | DLSS5 / 第一人称 / 服装 Mod / 乳摇 都能单独开关（可逆） |
| **启动前风险确认** | 在拉起游戏之前先查"这套 Mod 会不会崩"（资源冲突 + 过去崩过的组合），有风险就说清是什么冲突，由你决定要不要继续 |
| **崩溃归因** | 崩了会区分"Mod 资源冲突"与其它原因，并生成一份带完整现场的诊断包（含游戏日志与本次归因） |
| **Mod 修复 / 回滚**（实验性） | 游戏版本更新后老 Mod 常需"适配"，在卡片上就能一键修；**改前自动整份备份、可一键回滚** |
| **游戏目录净化 / 还原** | 把第三方注入物先备份再移走，随时一键还原 |
| **更新** | 程序本体与各组件都能检查、更新 |
| **摆姿 / MMD**（可选） | 集成 Endfield Poser，用它自带的页面摆姿势、放 MMD |

## 怎么用

1. **下载**：Release 里是一个 `EndfieldModController.exe` + 一个 `assets-bundle.zip`（后者首次启动会自动下载，也可以手动放到 exe 同目录）。
2. **双击 exe**：它会自己要求管理员权限（弹一次 UAC，点"是"）。
   放到一个**你有写权限的普通目录**就行 —— 别放 `Program Files` 这类只读目录，也别放临时目录。
3. **点「一键启动」**：第一次可能提示"请再点一次"（那是让 XXMI 先生成它自己的配置），按提示来即可。
4. **进游戏**：DLSS5 **不需要任何手动配置**，进去看面板里的「成功NR帧」涨起来就是生效了。
5. **加 Mod**：把 `.zip` **拖到窗口任意处**（在「Mod 库」页）→ 勾选 → 点「生成控制器」；之后照旧一键启动。

## 遇到问题

- 每一次自检、每一步动作都会写进程序的**启动日志**（设置页里可以直接打开）。
- 游戏异常退出时，程序会**自动生成一个崩溃包**（含游戏日志、崩溃转储、注入快照，以及本次退出的**归因**）—— 把它发到 [Issues](https://github.com/jing-hy/EndfieldModController/issues) 就能定位。
- 更细的排查顺序（DLSS5 不出帧怎么按步看、崩溃怎么分因、Mod 冲突怎么清）→ **[详细文档](docs/README.detailed.md)**。

## 第三方组件与许可

本程序**只做分发与编排**，不修改任何组件的源码，版权归各自作者：

| 组件 | 用途 | 许可 / 说明 |
| --- | --- | --- |
| [XXMI Launcher](https://github.com/SpectrumQT/XXMI-Launcher) / [XXMI Libraries](https://github.com/SpectrumQT/XXMI-Libs-Package) / [EFMI](https://github.com/SpectrumQT/EFMI-Package) | 注入器与服装 Mod 引擎 | MIT，从官方仓库下载 |
| [3DMigoto](https://github.com/bo3b/3Dmigoto) | EFMI 的底座 | MIT |
| [ReShade](https://reshade.me/) | 后处理底座（Addon 版） | BSD-3 |
| [RenoDX](https://github.com/clshortfuse/renodx) / Endfield Enhancer | DLSS5 神经渲染 / 第一人称（英文原版） | MIT |
| **第一人称中文补丁** —— B站 up 主 **Hirahido** | 第一人称面板的中文版 | 版权归原作者；随包分发，作者若不愿可联系我们移除 |
| [iMMERSE](https://github.com/martymcmodding/iMMERSE)（Marty's Mods） | 后处理链 | MIT |
| DLSS 5 Feed | 给 DLSS5 喂颜色 / 运动矢量 / 深度 | 无公开仓库，随包分发 |
| [SecondaryMotion](https://github.com/Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics)（乳摇） | 物理效果 | 见上游仓库，随包分发最小注入集 |
| [Endfield Poser](https://github.com/OedoSoldier/Endfield-Poser) | 摆姿 / MMD 播放（可选） | **AGPL-3.0** —— **不随包分发**，只从官方 Release 下载并调用它自己的安装向导 |
| **Endfield PS-T DrawSection Fix**（实验性） | 修老 Mod | **B站 up 主 可可HXL**《终末地Mod修复工具包》v1.5；**闭源**、随包分发，版权归原作者 |
| NVIDIA NGX 运行库 | DLSS 与神经渲染 | NVIDIA 版权，随包仅为免去手动下载 |

本项目自身为 **MIT** 许可。任何组件的作者若对分发方式有意见，欢迎开 issue，我们会立即调整。

## 免责声明

- 本程序**不是**官方工具，与鹰角网络 / Hypergryph 无关。
- 使用 Mod 可能违反游戏用户协议，**风险由使用者自负**。
- 程序会读写游戏目录中的**注入类文件**，但一律先备份、并提供一键还原；**不会**修改游戏本体、资源与存档。
- 第三方组件由其原作者维护，相关问题请先到对应仓库反馈。
