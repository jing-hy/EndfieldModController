<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# AGENTS.md

本仓库给 AI 助手的说明是 **[AGENTS.md](AGENTS.md)** —— 请读那一份。

它讲三件事：排查故障时先看什么、改完代码要同步什么、交活前自查什么。

- 维护者清单（提交前必读）：[CONTRIBUTING.md](CONTRIBUTING.md)
- 手测清单：[TESTING.md](TESTING.md)
- 使用者说明：[README.md](README.md)

## 本项目自带的技能（skill）

放在 [.agents/skills/](.agents/skills/)，任何支持 skill 的客户端都可以直接读：

| skill | 什么时候用 |
| --- | --- |
| [emc-new-managed-component](.agents/skills/emc-new-managed-component/SKILL.md) | 把第三方组件接成"受管组件"（依赖页 + 开关 + 自检 + 更新） |
| [emc-diagnostics-triage](.agents/skills/emc-diagnostics-triage/SKILL.md) | 用户拿诊断包/日志报故障时的排查路线 |
| [emc-structure-closeout](.agents/skills/emc-structure-closeout/SKILL.md) | 改完源码的收尾：测试 / 前端产物 / 结构树 / 构建进 modtest |

> ⚠️ 这里**故意不做符号链接**（`deepseek-harness` 那类是 `CLAUDE.md → AGENTS.md`）。
> 本项目在 Windows 上开发与发布，git 符号链接要 `core.symlinks` + 管理员权限才能正常 checkout，
> 对普通用户太脆 —— 所以用"一行指路"代替，内容只维护一份（`AGENTS.md`）。
