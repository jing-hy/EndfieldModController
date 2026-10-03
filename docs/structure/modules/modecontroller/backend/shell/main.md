---
uid: b1d12009
id: modecontroller.backend.shell.main
parent: modecontroller.backend.shell
tags: [entry]
name: {zh: "主入口", en: "Main Entry"}
description:
  zh: >
      把程序拉起来：拒绝第二个实例、清掉会堆在 temp 里的 _MEI 解压残留，后端就绪前先用一张静态加载页把窗口显示出来，再把控制权交给 pywebview。 ⚠️ 单实例判据 2026-10-03 升级：锁里的 PID 活着 **且**（进程指纹（exe 路径 + 创建时间）对得上 **或** 屏幕上真有我们的窗口）才算“已有实例”，否则视为陈旧锁 / PID 被复用并**直接接管** —— 旧判据只看 PID 存活，PID 被 Windows 复用后会永久误判成“已在运行”并静默退出（反馈者原话「关掉管理器，显示要管理员权限，然后就没反应了」）。真的还有一个实例时，会把那个窗口拉到最前面；退出时把锁还回去。
      
  en: >
      Start the program: refuse a second instance, clean stale _MEI folders in temp, show a static splash before the backend is ready, hand control to pywebview. The single-instance test needs the PID alive AND (process fingerprint matched OR one of our windows on screen); otherwise the lock is stale and is taken over. A real running instance gets its window brought to the front; the lock is released on exit.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.319Z"
fingerprint: cb3aa853877a45d0b38aa72888961f66611abe16b2189554163208d48ccf5489
source:
  - path: "endfieldmodcontroller/app.py"
    line: 1
    end_line: 345
  - path: "endfieldmodcontroller/app.py"
    line: 347
    end_line: 463
apis:
  - protocol: rpc
    path: "app.main"
    description:
      zh: >
          进程入口：单实例互斥、后端就绪前先用静态加载页把窗口显示出来、绑定 js_api、起循环。
          
      en: >
          Process entry: single-instance guard, splash window before the backend is ready, bind js_api, run the loop.
          
  - protocol: rpc
    path: "app._cleanup_stale_mei_dirs"
    description:
      zh: >
          清掉残留的 `_MEI` 解压目录（否则会在 temp 里永久堆积）。
          
      en: >
          Clean stale _MEI extraction folders (otherwise they pile up in temp forever).
          
  - protocol: rpc
    path: "app._already_running"
    description:
      zh: >
          是否已有实例在跑：锁里 PID 活着 + 进程指纹匹配（或屏幕上有我们的窗口）；PID 被复用则接管锁。
          
      en: >
          Is another instance running: the locked PID is alive plus its fingerprint matches (or one of our windows exists); a recycled PID means take the lock over.
          
  - protocol: rpc
    path: "app._focus_our_window"
    description:
      zh: >
          双击图标时把已开着的窗口拉到最前面（否则用户看到的就是“没反应”）。
          
      en: >
          Bring the already-open window to the front when the icon is double-clicked.
          
deps:
  - kind: call
    to: modecontroller.backend.api.state
    label: {zh: "构造 API", en: "Builds the API"}
---
