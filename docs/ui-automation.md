<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# UI 自动化 / 无障碍通道

让**脚本或 AI** 操作这个管理器的界面：切换页面、点开关、拖动滑块、滚列表。
它是给自动化用的，不影响正常使用；命令走的是**真实的界面交互**（等价于人手点一下），
所以界面上看到的变化与真正生效的状态完全一致。

## 一、在哪

程序一启动就会在本机起一个 HTTP 接口（只绑 `127.0.0.1`，不对外网开放）：

```
<程序目录>\runtime\_state\ui_api.json
```

里面是：

```json
{
  "url": "http://127.0.0.1:51234",
  "port": 51234,
  "token": "启动时随机生成的一串字符",
  "pid": 12345,
  "started_at": "2026-11-17 23:59:00"
}
```

端口是随机的，**token 每次启动都换**——所以别把它抄进脚本，读这个文件即可。
程序退出时这个文件会被删掉。

## 二、三个接口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/health` | 探活（不需要 token）：`{"ok": true, "pid": ...}` |
| `GET` | `/state` | 界面快照：当前页面 + 所有**可见可交互**元素 |
| `POST` | `/act` | 执行一个动作：`{"id": ..., "action": ..., "value": ...}` |

`/state` 与 `/act` 都要带 token：请求头 `X-MC-Token: <token>`（或 `?token=` 查询参数）。

### `/state` 返回什么

```json
{
  "ok": true,
  "tab": "library",
  "title": "终末地 Mod 管理器",
  "viewport": {"width": 1180, "height": 800},
  "count": 42,
  "elements": [
    {
      "id": "[data-mc-id=\"tab:settings\"]",
      "role": "button",
      "label": "设置",
      "tag": "button",
      "disabled": false,
      "bounds": {"x": 8, "y": 300, "w": 190, "h": 34}
    },
    {
      "id": "div.card > button.switch:nth-of-type(1)",
      "role": "switch",
      "label": "",
      "checked": true,
      "tag": "button"
    }
  ]
}
```

要点：

- `id` 是**可用的 CSS 选择器**，直接传给 `/act` 就能操作它；
- 侧栏页面按钮带固定标识 `tab:<页面id>`（`library` / `assist` / `store` / `downloads` /
  `dependencies` / `launch` / `settings` / `about`），页面之间的切换不用靠猜位置；
- 其余元素的选择器是 DOM 路径，页面内容变化后**要重新 `/state` 取**，不要缓存。

### `/act` 支持的动作

| action | value | 说明 |
| --- | --- | --- |
| `click` | 不需要 | 点击元素（按钮、链接、开关都行） |
| `set` / `toggle` | `true` / `false` | 把开关类元素置开或置关（已经是目标状态就不动） |
| `value` / `type` | 文本 | 给输入框赋值（会触发 input/change，等同人输入） |
| `scroll` | 不需要 | 把元素滚到视野中间 |
| `scroll-by` | 像素数 | 页面整体滚动（正数向下） |
| `focus` | 不需要 | 只聚焦，不点 |

返回结果里带 `ok`、`action`，以及操作后该元素的**最新状态**（`checked` / `value`）。

## 三、怎么用

### 命令行（推荐，需要 Python）

```powershell
python scripts\ui_ctl.py state                  # 看当前页面和所有可点元素
python scripts\ui_ctl.py find 壁纸              # 按文字找元素（拿到 id）
python scripts\ui_ctl.py tab settings           # 切到设置页
python scripts\ui_ctl.py set '[data-mc-id="x"]' on
python scripts\ui_ctl.py value 'input#search' "终末地"
python scripts\ui_ctl.py scroll-by 400
```

加 `--json` 输出原始 JSON，适合程序解析。

### curl / 任何 HTTP 客户端

```powershell
$i = Get-Content runtime\_state\ui_api.json | ConvertFrom-Json
Invoke-RestMethod "$($i.url)/state" -Headers @{ "X-MC-Token" = $i.token }
Invoke-RestMethod "$($i.url)/act" -Method Post -Headers @{ "X-MC-Token" = $i.token } `
  -ContentType "application/json" -Body '{"id":"tab:launch","action":"click"}'
```

### 给 AI 的标准流程

1. `GET /state` 拿到 `tab` 与 `elements`；
2. 按 `label`（按钮上的文字）找到目标元素的 `id`；
3. `POST /act` 用那个 `id` 执行 `click` / `set` / `value`；
4. 需要的话再 `GET /state` 确认结果（例如开关的 `checked` 变没变）。

> 状态确认要看**界面上真的变了**（`checked` / `value` / `tab`），而不是只看 `/act` 回了 OK。

## 四、限制与注意事项

- **只在程序开着时可用**；程序关了 `ui_api.json` 也就没了。
- 命令是排队交给界面执行的，界面**没响应**时（窗口最小化到底、界面卡死）会在约 8 秒后
  如实返回「界面没有响应」，不会假装成功。
- 只列**当前可见**的元素：弹窗没打开、页面没切过去时，里面的元素不在快照里 ——
  这也意味着它遵守界面自己的规则（比如需要先点某按钮才会出现的开关）。
- 通道只绑 `127.0.0.1`，其他机器连不上；同一台机器上的任何程序都能读那个 json 文件，
  所以它是"**本机可信环境**"的自动化通道，不是给不受信任环境的远程控制。
- 它只操作界面，**不会**绕过界面直接改配置或文件 —— 你要的效果必须界面本身支持。

## 五、排错

| 现象 | 原因 / 做法 |
| --- | --- |
| 找不到 `runtime\_state\ui_api.json` | 管理器没在运行；或程序版本太老（还没有这个功能） |
| `/state` 返回 401 | token 不对（用文件里那份，注意每次启动都会换） |
| 返回「界面在 8 秒内没有响应」 | 窗口还没创建好、或者界面正忙 —— 等窗口起来再试 |
| 元素 id 找不到 | 页面变了，重新 `GET /state`；不要缓存上一次的 id |
