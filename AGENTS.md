# 给 AI 助手的说明

本仓库是《明日方舟：终末地》Mod 管理器 **EndfieldModController** 的源码。

> 人看的维护者清单在 [CONTRIBUTING.md](CONTRIBUTING.md)（提交前必读）；
> 使用者说明在 [README.md](README.md)；手测清单在 [TESTING.md](TESTING.md)。
> 本文件只讲一件事：**你用 AI 来排查这个程序的故障时，该怎么做、做到哪一步。**

---

## 一、如果你在排查某个用户的故障

1. **先看证据，再动代码。** 诊断包（`diagnostics-*.zip`）里主要是这几样：
   - `summary.txt` —— 采集总览、退出码释义、关键路径
   - `logs/` —— 本程序自己的日志（`launch.log` 等）
   - `player/` —— **游戏自己写的** `Player.log`（判"走到哪一步"必看）
   - `reshade-*` —— ReShade 的日志与生效配置
   - `injection-trace.jsonl` —— 各个时刻（启动前 / 游戏启动后 / 退出 / 崩溃）的注入库与进程模块快照
   - `dlss5-*` —— DLSS5 那一侧（preset、addon 位置、shader 清单、feed 日志）

2. **判据不够就直说"还缺什么"**，不要硬给一个"听起来合理"的结论 —— 错误归因会把排查带偏、让人白折腾。

3. **能复现就复现**：同一环境下**只改一个变量**再跑一次，比读十遍代码有用。对照实验才是因果（"特征吻合"不是）。

4. **看到某个文件缺失/报错，先确认它是不是由本程序负责的** —— 相当一部分日志噪音来自第三方（ReShade 的 shader 编译失败、addon 版本不兼容等），那些**不影响功能**，不需要改代码。

---

## 二、查明是**本程序**的问题时

**直接修好并提 PR**，这是最有帮助的回馈方式。

仓库：<https://github.com/jing-hy/EndfieldModController>

动手前请读 [CONTRIBUTING.md](CONTRIBUTING.md)，那里写清了边界与提交前的检查。三条**硬边界**（越线就是白干）：

1. **只改本仓库**：`endfieldmodcontroller/`（后端）、`frontend/`（Vue 源码）、`web/`（构建产物）、`scripts/`、`tests/`、文档。
2. **不动第三方依赖本体**：XXMI Launcher / EFMI / ReShade / SecondaryMotion（乳摇）/ Endfield Poser / OptiScaler —— 它们是别人维护的，改了别人也从 GitHub 重新拉，我们的改动会**静默失效**。它们自身的问题请提到它们自己的仓库。
3. **`library/` 是用户的 Mod 库，只读**：不删、不移、不重命名、不换位置、不"整理"。唯一允许的删除入口是用户自己在卡片菜单点「移出 Mod 库」。

提交前**至少**跑一遍（必须全绿）：

```bash
python -m pytest tests -q
```

> 改过 `frontend/` 的话，记得先 `node node_modules/vite/bin/vite.js build`（产物 `web/dist/index.html` 才是程序实际加载的界面）。
> 发版与版本号规则见 [CONTRIBUTING.md](CONTRIBUTING.md) 第二节 —— **未经维护者明确同意不要发 Release**。

---

## 三、拿不准、或者不方便提 PR 时

用 **QQ 群**反馈即可，**不需要先自己修好**：

- 群号 **1045239747**（加群验证答案 **`jing_hy`**）
- 说清**现象** + 附上**诊断包**就够

也可以直接在本仓库的 [Issues](https://github.com/jing-hy/EndfieldModController/issues) 发帖（附诊断包）。

---

## 四、如果查明是第三方组件的问题

XXMI Launcher / EFMI / ReShade / SecondaryMotion / Endfield Poser / OptiScaler 的问题 **→ 去对应上游仓库提 issue**。

本程序只做「**编排、自检、补齐、备份与还原**」：负责把组件装对、把注入铺对、把故障查清并给出可读的原因；不重写别人工具的 UI，也不改它们的源码。
