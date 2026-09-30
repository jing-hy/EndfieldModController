<p align="center">
  <img src="assets/app_256.png" width="132" alt="EndfieldModController">
</p>

# EndfieldModController

《明日方舟：终末地》的一站式 Mod 管理器：把 **DLSS5 神经渲染 + 第一人称视角 + 服装 Mod（EFMI）+ 乳摇物理 + 摆姿 / MMD 播放**统一到一次「一键启动」里；运行环境从零自动装好，**零配置启动即用**。

Windows 桌面程序（Python + Pywebview），单文件 exe。当前版本 **0.6.0** —— [下载最新版](https://github.com/jing-hy/EndfieldModController/releases)

> 📖 安装细节、目录结构、逐项故障排查、开发与发布流程 → **[详细文档](docs/README.detailed.md)**

---

## 一、它能做到什么

| 能力 | 说明 |
| --- | --- |
| **从零装好环境** | 首次启动自动下载安装 XXMI Launcher、XXMI Libraries、EFMI 三个组件（带校验），装完写好配置 |
| **Mod 库管理** | 把 `.zip` 拖到页面任意处即可导入；自动解压并尝试识别角色，拿不准就问你要哪个角色 |
| **同角色互斥** | 同一个角色只保留一个 Mod —— 同时加载两个同角色 Mod 会把游戏搞崩 |
| **一键启动** | 维护注入库、补齐缺失组件、跑完整初始化自检，然后拉起 XXMI |
| **插件开关** | DLSS5、第一人称、服装 Mod、乳摇都能单独开关（靠移动文件实现，可逆） |
| **启动前风险确认** | 在拉起游戏之前先查"这套 Mod 会不会崩"（资源冲突 + 过去崩过的组合），有风险就说清是什么冲突，由你决定要不要继续 |
| **崩溃归因** | 崩了会区分"Mod 资源冲突"与其它原因，并生成一份带完整现场的诊断包，直接发 issue 即可 |
| **Mod 修复 / 回滚**（实验性） | 游戏版本更新后老 Mod 常需适配，在 Mod 卡片上就能一键修；**改前自动整份备份、可一键回滚** |
| **游戏目录净化 / 还原** | 把第三方注入物**先备份再移走**，随时一键还原；被移走的系统模块会自动补回 |
| **更新** | 程序本体与各组件都能检查、更新 |
| **摆姿 / MMD 播放**（可选） | 集成 Endfield Poser，用它自带的页面摆姿势、放 MMD |

## 二、它是怎么工作的

一次「一键启动」做四件事：**补齐运行环境 → 维护注入库 → 跑初始化自检 → 拉起 XXMI**；你只需要在 XXMI 界面点 Start。

游戏进程里同时存在这些东西，全部由注入库决定：

```text
 唯一的一个 ReShade 底座
   ├─ DLSS5 神经渲染
   ├─ 第一人称 / 相机
   ├─ 面板汉化
   ├─ 喂帧组件（给 DLSS5 提供颜色 / 运动矢量 / 深度）
   └─ 后处理 shader
 服装 Mod 引擎（EFMI）
 乳摇注入代理
 摆姿 / MMD 注入代理（可选）
```

三条关键设计：

1. **一个游戏进程只能有一个 ReShade 底座** —— 所以本程序把 DLSS5 与第一人称合到同一个底座上，不会塞两份；这也是"两个整合包混着用必崩"的原因。
2. **不改游戏本体** —— 写进游戏目录的都是注入类文件，改动前一律先备份、随时一键还原；游戏本体、资源、存档一律不碰。
3. **不内置 Mod** —— Mod 都是你自己放进去的；程序负责解压、识别角色、同角色互斥，以及在启动前把可能崩的组合拦下来。

## 三、怎么用

### 第一次使用

1. 到 [Release](https://github.com/jing-hy/EndfieldModController/releases) 下载 `EndfieldModController.exe`（同页还有一个 `assets-bundle.zip`，首次启动会自动下载）；
2. 放到**你有写权限的普通目录**再双击 —— 别放 `Program Files` 这类只读目录，也别放临时目录（程序的数据与你的 Mod 库就在 exe 旁边）；
3. 点「**一键启动**」。第一次可能提示"请再点一次"（那是让 XXMI 先生成它自己的配置），照提示来即可。

之后进游戏就行：**DLSS5 不需要任何手动配置**，看 ReShade 面板里的「成功NR帧」涨起来就是生效了。

### 日常使用

- **Mod 库页**：把 `.zip` 拖进来即导入；勾选（同角色自动互斥）后点「生成控制器」。每个 Mod 卡片右下角有「⋯」，鼠标移上去即可**修复 / 回滚 / 打开所在文件夹 / 移出库**。
- **启动页**：一个大号「一键启动」+ 几个插件开关（DLSS5 / 第一人称 / 服装 Mod / 乳摇 / 摆姿）+ 日志窗。
- **设置页**：自检、组件更新、诊断包、游戏目录还原、路径与外观等都在这里。
- **摆姿 / MMD（可选）**：游戏运行时可以用它自带的页面摆姿势、放 MMD。

## 四、常见问题

**Q：DLSS5 面板显示开着，但「成功NR帧」不动？**
先看启动日志里自检有没有报错；再确认游戏内超分选的是 **DLSS**（选 FSR / XeSS 时神经渲染不会绑定）。更细的排查顺序见详细文档。

**Q：游戏崩了 / 加载中闪退？**
程序会生成崩溃包并给出**归因**：如果是 Mod 资源冲突，弹窗会直接列出是哪两个 Mod，去 Mod 库取消勾选其中一个再启动即可；其它原因也会带上完整现场，把崩溃包发到 Issues 就能定位。

**Q：第一次点「一键启动」被提示"再点一次"？**
正常 —— XXMI 的配置要它自己跑一次才会生成，程序先替你拉起来生成，再点一次就好。

**Q：Mod 装了很多，进游戏没生效？**
先确认对应开关是开的（服装 Mod / 乳摇 / DLSS5 各自独立），再看自检结果；同一角色只会保留一个 Mod，勾选后记得点「生成控制器」。

**Q：游戏版本更新后老 Mod 失效？**
用 Mod 卡片「⋯」里的「**修复**」（实验性）——它会适配资源槽位号，**改前自动备份、可一键回滚**。

## 五、第三方组件与许可

本程序**只做分发与编排**，不修改任何组件的源码，版权归各自作者：

| 组件 | 用途 | 许可 |
| --- | --- | --- |
| [XXMI Launcher](https://github.com/SpectrumQT/XXMI-Launcher) / [XXMI Libraries](https://github.com/SpectrumQT/XXMI-Libs-Package) / [EFMI](https://github.com/SpectrumQT/EFMI-Package) | 注入器与服装 Mod 引擎 | MIT |
| [3DMigoto](https://github.com/bo3b/3Dmigoto) | EFMI 的底座 | MIT |
| [ReShade](https://reshade.me/) | 后处理底座（Addon 版） | BSD-3 |
| [RenoDX](https://github.com/clshortfuse/renodx) / Endfield Enhancer | DLSS5 神经渲染 / 第一人称（英文原版） | MIT |
| **第一人称中文补丁** —— B站 up 主 **Hirahido** | 第一人称面板的中文版 | 版权归原作者 |
| [iMMERSE](https://github.com/martymcmodding/iMMERSE)（Marty's Mods） | ReShade 后处理链 | MIT |
| DLSS 5 Feed | 给 DLSS5 喂颜色 / 运动矢量 / 深度 | 见其说明（无公开仓库） |
| [SecondaryMotion](https://github.com/Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics)（乳摇） | 物理效果 | 见上游仓库 |
| [Endfield Poser](https://github.com/OedoSoldier/Endfield-Poser) | 摆姿 / MMD 播放（可选） | **AGPL-3.0** —— **不随包分发**，只从官方 Release 下载并调用它自己的安装向导 |
| **Endfield PS-T DrawSection Fix**（实验性） | 修老 Mod | **B站 up 主 可可HXL**《终末地Mod修复工具包》v1.5；版权归原作者，**随包分发** |
| NVIDIA NGX 运行库 | DLSS 与神经渲染 | NVIDIA 版权，随包仅为免去手动下载 |

**特别声明**：随包分发的第一人称**中文**补丁由 **B站 up 主 Hirahido** 制作，版权归其所有；Mod 修复工具由 **B站 up 主 可可HXL** 制作，版权归其所有。本程序只做分发与安装编排、不修改其内容 —— 两位作者若不希望被随包分发，请在 issue 里说明，我们会立即移除。

本项目自身为 **MIT** 许可。

## 六、免责声明

- 本程序**不是**官方工具，与鹰角网络 / Hypergryph 无关。
- 使用 Mod 可能违反游戏用户协议，**风险由使用者自负**；请自行确认你所在环境的规则。
- 程序会读写游戏目录中的**注入类文件**，但一律先备份、并提供一键还原；**不会**修改游戏本体、资源与存档。
- 第三方组件由其原作者维护，相关问题请先到对应仓库反馈；本程序的集成问题欢迎开 issue。

---

> 需要安装细节、目录结构、逐项故障排查、开发与发布流程 → **[详细文档](docs/README.detailed.md)**
