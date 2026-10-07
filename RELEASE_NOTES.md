# v1.2.1

本次更新修复三个实际影响功能的问题：DLSS5 神经渲染在部分机器上不出帧、Streamline 运行库从未自动部署（#16）、以及依赖更新的进度显示成天文数字；同时扩充了诊断包的采集范围。

## 一、修复：DLSS5 神经渲染不出帧

### 现象

游戏可以正常进入，但神经渲染不生效，`dlss5-feed.log` 中出现：

```
[feed] motion-vector provider MartysMods_Launchpad is installed but DISABLED:
       enable it above DLSS 5 Feed.
NR-VERDICT v3 state=UNAVAILABLE
```

### 根因

ReShade 的 technique 全名是 `<Technique>@<effect 相对路径>`。运动矢量来源 `MartysMods_LAUNCHPAD.fx` 位于 `reshade-shaders\Shaders\iMMERSE\` 子目录，而写进 preset 的名字缺少这一层目录：

```
写入：MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx
识别：MartysMods_Launchpad@iMMERSE\MartysMods_LAUNCHPAD.fx
```

ReShade 因此识别不到该 technique，将其视为未启用。缺少运动矢量时，神经渲染只对静止画面有效，动态画面等同于没有效果（`DLSS5_Feed.fx` 在 shaders 根目录，因此它不带目录前缀是正确的，这也是该问题不易察觉的原因）。

同时，自检虽然一直报告 `fixed=True`，文件内容却从未改变：合并 preset 行时按 `@` 之前的技术名去重，两种写法的技术名相同，于是旧的短名字被判为「已存在」而跳过替换。

### 修复

- technique 全名按 effect 在磁盘上的**实际相对位置**计算，不写死目录名，shader 包更换子目录时自动跟随。
- 同名 technique 但路径不一致时，以正确路径替换旧条目。
- 判据与扫描正则同步收紧：只认带正确相对路径的全名；此前正则的字符类不含路径分隔符，带目录的合法写法反而会被误判为「未启用」。

## 二、修复：Streamline 运行库从未自动部署（#16）

### 根因

`deploy_streamline_libs()` 的调用条件是 `mfg_unlock_enabled`（多帧生成开关）。多帧生成在先前版本中已判定对该游戏无效并默认停用，因此该条件恒为假，「命中判据就修复运行库」这条路径从未执行。

实际后果：依赖页已下载约 263 MB 的 Streamline 运行库，游戏目录中仍是游戏自带的旧版（`sl.common.dll` 674,432 字节，新版为 843,392 字节）。

### 修复

部署条件改为「多帧生成开启 **或** 运行库需要修复」；部署与下载共用同一套判据，避免两侧判据漂移。

## 三、修复：依赖更新的进度显示成超大数字

字节回调每 256 KB 触发一次，回调给出的是「当前这一个文件的累计已下载值与总大小」。原实现无条件累加，一个 240 MB 的安装包在下完时会累加成约 230 GB，界面显示形如 `88968.2 MB / 246303.5 MB`（百分比仍然正确，只有数值失真）。

改为按组件 key 记账：同一组件重复回调时覆盖该组件的值，切换到下一个组件时才并入总量。

## 四、诊断包扩充

新增三项采集，用于在无法直接访问出问题机器的前提下定位上述类型的问题：

- `dlss5-ReShadePreset.ini`：technique 的全名与启用状态所在文件（`ReShade.ini` 只提供路径，`ReShade.log` 只体现识别结果）。
- `dlss5-addon-placement.txt`：addon 在根目录与 `_disabled\` 中的分布，用于区分「插件被停用」与「插件未铺」。
- `dlss5-shaders-tree.txt`：shader 的相对路径清单，判定 technique 全名是否正确的唯一依据。

## 五、其他

- 商城的图片链路改为进程内本地只读服务，列表使用 220 档缩略图并按视口懒加载。
- Mod 库新增「角色视图」开关（默认关闭）：开启后先按角色排列，点进去查看该角色的 Mod。
- 角色表与角色头像随 exe 分发，离线可用。
