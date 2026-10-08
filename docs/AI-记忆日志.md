# AI 记忆日志（自动生成，请勿手改）

> 这份文件由 `scripts/memory_log.py` 从工作区记忆库导出，**每次 `push.py` 推送前自动刷新**。
> 目的：让「当时为什么这么改、踩过什么坑」跟着源码一起留在仓库里。
> 想改内容 → 改记忆库（用记忆工具），再跑一次本脚本；不要直接编辑本文件。

- 生成时间：2026-10-08 21:24:24
- 来源：`.dsh-meow/memory.db`
- 条目：3 条（已跳过 archived / 其它项目的条目）

---

## 项目记忆（结构 / 决策 / 部署 / 待办）（2 条）

### 项目结构

### EMC 的远程通知机制：唯一发布入口是仓库根 alert…
*2026-10-08 21:22*

EMC 的远程通知机制：唯一发布入口是仓库根 alerts.json（改完 push main 即生效，不用发版）。两档：info/warning=公告（启动首屏就绪后弹一次、按 id 记已读、不拦启动）；critical=异常状态预警（每次点「一键启动」都强制弹、不记已读、无开关、强制停留 hold_seconds 默认 10 上限 120、三选一：还原配置〔关全部注入+备份移走游戏目录第三方文件，可撤销〕/保持配置不启动/仍然启动）。客户端经 api.github.com contents 每次真查，失败回退 raw 网页路线（经 fastnet 第三方镜像）再用上次成功缓存。版本区间 min_version/max_version 留空=所有版本可见，critical 同样受该区间限制。截至 2026-10-08 该文件只有 2 条 warning + 1 条 info，git 全历史从未发过 critical。

`关键词：["alerts.json","异常状态预警","critical","公告","一键启动","强制停留","还原配置","版本区间","镜像线路","push 即生效","hold_seconds"]`

### 部署与数据

### EMC = jing-hy/EndfieldModCon…
*2026-10-08 21:13*

EMC = jing-hy/EndfieldModController（《明日方舟：终末地》一站式 Mod 管理器，Python 后端 + Vue 前端）。本地工作区 D:\emc，以 git init + remote add origin + fetch + checkout 方式落地（origin=https://github.com/jing-hy/EndfieldModController.git，main 跟踪 origin/main），.dsh-meow/ 已写入 .git/info/exclude。2026-10-08 拉取时 HEAD=f8e0368（随 1.2.3-beta 同步结构树），latest release=v1.2.2。

`关键词：["EndfieldModController","EMC","终末地","Mod管理器","D:\\emc","origin/main","工作区","1.2.3-beta","v1.2.2","源码仓库","git checkout"]`

## 经验教训（被纠正过的、踩过的坑）（1 条）

### 用本机用户级 GH_TOKEN 让 git 拉 GitH…
*2026-10-08 21:13*

用本机用户级 GH_TOKEN 让 git 拉 GitHub 仓库时，-c http.extraheader="AUTHORIZATION: bearer <token>" 会报 invalid credentials；可行做法是注入 $env:GH_TOKEN 后执行 git -c credential.helper= -c "credential.helper=!gh auth git-credential" fetch origin。

`关键词：["git fetch","GH_TOKEN","credential.helper","gh auth git-credential","http.extraheader","invalid credentials","认证失败","GitHub 拉取","git clone"]`

