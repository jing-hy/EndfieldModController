<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# v1.4.0

本次更新新增「离线依赖包」（给无法访问 GitHub 的机器应急用），修好一个"部分随包资产缺失时永远不会自动补齐"的缺陷，并把测试与构建固定为串行。

## 一、新增：离线依赖包（依赖页顶部「导入依赖包…」）

**给谁的**：网络连不上 GitHub / reshade.me 的机器。依赖页顶部新增「导入依赖包…」，导入后各组件的原始安装包会落到本地离线目录，安装链路**离线源优先**（命中就不发任何网络请求），再点一次「下载并补齐组件」或一键启动即完成配置。

**包里有什么**：XXMI Launcher、XXMI Libraries、EFMI、ReShade 底座、DLSS5-Feeder、iMMERSE、**Endfield Poser**（AGPL-3.0，随附许可全文、版权声明与源码地址）、**Streamline 运行库**（MIT，只含运行所需的 9 个 dll），以及完整随包资产（DLSS 运行库、shaders / textures 等）。不含 VC++ 运行库（微软条款：必须跑官方安装器）。

**导入前逐条校验**：清单能解析、每个声明的文件都在包里、`sha256` 对得上、无目录穿越；任何一条不过就**一个文件都不落盘**。旧的 `assets-bundle.zip` 与单份组件 zip 也认（自动分派到原有链路）。

**获取方式**：不随 Release 发布，只在无法访问 GitHub 时作应急分发（QQ 群 1045239747，验证答案 `jing_hy`）。构建脚本为 `scripts/build_deps_bundle.py`，本地按需运行。

## 二、修复：部分随包资产缺失时，永远不会自动补齐

**现象**：面板显示「未安装 NR 运行时」，ReShade 报 `Failed to compile '...DLSS5_Feed.fx': could not open included file 'ReShade.fxh'`，而自检每次都报同样的三条警告、谁也补不上。

**根因**：只下载了单文件 exe 的机器上，exe 内嵌了 `assets\dlss5\`（三个 addon），于是「任一组有清单就算本地已有 assets」与「清单非空就不去取资产包」两条判据同时被满足 —— 而 `assets\nvngx\`（DLSS 运行库分卷）与 `shaders` / `textures`（ReShade 标准头与贴图）只存在于 `assets-bundle.zip` 里，因此永远补不上。

**修复**：判据改为「**每一组资产都得有来源**」才算齐全；缺任意一组就会去取一次资产包（失败按既有约定重试）。同时去掉了"没有清单就直接返回"的早退分支 —— 那条路恰恰是唯一能补齐它的路。

## 三、调整：测试与构建一律串行

`scripts/run_tests.py` 移除了"按 CPU 占用 / 测试文件数量决定并发"的全部逻辑，固定串行（自行传 `-n N` 除外）。原因：这套测试是文件 IO 密集型（复制 / 解压 / 扫描真实目录），并行 worker 互相拖慢；且 `pytest-xdist` 是多进程，跨进程共享缓存会带来随机失败。

## 四、其他

- **组件版本表同步上游**：XXMI Launcher 更新到 v2.4.6、Endfield Poser 更新到 0.5.71（其余四项核对后本就一致）。
- **日志分级与失败引导**：下载失败时日志以红色标注，并弹窗建议改用离线依赖包（附群号与导入入口）；全部就绪时以绿色一行收尾。中途的"换线路 / 重试"仍属正常自动切换，不会被当成失败。
- `test_one_click_launch_never_downloads_the_sdk` 与环境解耦：此前在留有历史 `Player.log`（含 `parseServerManifest` 报错）的机器上会恒定失败。
