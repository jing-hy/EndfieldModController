<script setup>
// 自更新入口（旧版是顶栏那个 `v0.9.x` 徽标；Vue 换皮时漏掉了，2026-10-03 用户发现）。
// 位置按用户要求：**左侧导航栏下面、主题色上面**。
//
// 三种状态：
//   ① 普通       —— 显示当前版本，点了主动检查一次
//   ② 有新版     —— `v当前 → v新版` + 高亮，点了下载并更新
//   ③ 已下载待装 —— 「重启以完成更新」，点了立刻应用（用户选过"稍后"会停在这）
import { ref, watch, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { store, onStateRefreshed } from "../store.js";
import { showAlert, showModalDialog, showToast } from "../lib/dialog.js";
import { Download, RefreshCw, CheckCircle2 } from "lucide-vue-next";

const current = ref("");
const latest = ref("");
const pending = ref(false);
const busy = ref(false);
const note = ref("");
// ⚠️ **下载更新包时的进度**（2026-10-03 用户：「安装日志不动、没速度、条在走」）——
// 自更新是后台下 28.4 MB 的 exe，原来界面上只有一句"正在处理…"，全程没有反馈。
// 后端的自更新任务就记在依赖任务里（`get_dependency_progress`），这里轮询它。
const dlPercent = ref(0);
const dlSpeed = ref(0);
// ⚠️ 必须是 ref：模板里 `v-if="dlTimer"` 要响应式更新（普通变量不触发重渲染）
const dlTimer = ref(null);
// 防重入：轮询可能连着几轮都看到"已下载"，别弹出多个确认框
const applying = ref(false);

// ⚠️ `humanSize` 复用 `lib/util.js`（2026-10-04）：本文件原先自己又抄了一份。本文件
// 原本还 import 了 `call`，所以这里改用命名导入（`call` 的导入在上面，不受影响）。
import { humanSize } from "../lib/util.js";

function stopPolling() {
  if (dlTimer.value) { clearInterval(dlTimer.value); dlTimer.value = null; }
}

async function pollDownload() {
  try {
    const p = await call("get_dependency_progress");
    const pct = Math.round(Number(p && p.percent) || 0);
    const spd = Number((p && p.speed_bps) || 0);
    dlPercent.value = Math.max(0, Math.min(100, pct));
    dlSpeed.value = spd;
    const running = !!(p && p.running);
    if (running) {
      note.value = `正在下载 v${latest.value || ""}：${dlPercent.value}%`
        + (spd > 0 ? `　${humanSize(spd)}/s` : "");
    } else {
      // 不跑了：按后端给的结果收尾
      stopPolling();
      const msg = String((p && p.message) || "");
      const ok = /已下载|完成/.test(msg);
      const failed = /失败/.test(msg);
      if (ok) {
        note.value = "更新包已下载，等待你选择何时安装";
      } else if (failed) {
        note.value = "更新失败";
      } else {
        note.value = "";
      }
      await load();
      // ⚠️⚠️ **下载完成后必须弹窗问"现在更新吗"**（2026-10-03 用户：
      //     「**下载完成就没了，没有弹窗询问是否现在更新**」）。
      // 后端是后台线程、`start_app_update()` 立刻返回，所以"下载完成"这个时刻
      // **只有轮询能发现**；原来的代码到这就把 `note` 一改就结束了，
      // 用户看到的是"下完了然后没了" —— 既不提示、也不安装。
      // 后端 `pending_apply=True` 时表示"包已就绪，等你决定"。
      if (ok && (p.pending_apply || p.pending)) {
        await askApply();
      } else if (failed) {
        await showAlert("更新失败", msg || "下载更新包没有成功，可以稍后再试。");
      }
    }
  } catch (e) { /* 拿不到就下一轮再试 */ }
}

/** 问用户要不要**立刻重启安装**（用户 2026-10-01 要求：下载完要弹窗让他选）。 */
async function askApply() {
  if (applying.value) return;          // 防重入：轮询可能连着触发
  applying.value = true;
  try {
    const now = await showModalDialog({
      title: "更新包已下载完成",
      message: `新版本已下载好（在 runtime\\_update\\ 里，不会丢）。\n\n`
        + `现在重启程序就会装上它，你的 Mod 库、配置与备份都不会动。\n`
        + `也可以选「稍后」，下次启动时会再提醒你。`,
      okText: "立即重启并安装", cancelText: "稍后",
    });
    if (now) {
      note.value = "正在安装…";
      await call("apply_app_update");   // 后端会替换 exe 并自动重启，这条调用不返回是正常的
    } else {
      note.value = "更新包已下载，可随时点这里安装";
    }
  } catch (e) {
    /* call() 已经弹过窗 */
  } finally {
    applying.value = false;
  }
}

onUnmounted(stopPolling);

function icon() {
  if (pending.value) return RefreshCw;
  if (latest.value) return Download;
  return CheckCircle2;
}

async function load() {
  try {
    const info = await call("get_app_info");
    if (info && info.version) current.value = String(info.version);
  } catch (e) { /* 拿不到就等下一次 */ }
  try {
    const p = await call("pending_update");
    pending.value = !!(p && p.pending);
  } catch (e) { /* 忽略 */ }
}

// ⚠️ 这里**不能只靠 onMounted**：Vue 里**子组件的 onMounted 先于父组件执行**，
// 而这个组件的父级（App.vue）要先 `waitForBridge()` 把前后端桥接好才轮到它 boot()。
// 于是 `call("get_app_info")` 在桥就绪前就发出去了、直接失败 ⇒ **当前版本号永远显示不出来**
// （用户 2026-10-03 截图反馈：左下角是 `v → v1.0.0`，前面那个版本号是空的）。
// 改成挂在 `store.ready` 上：桥一通就加载，之后每次状态刷新也顺手刷新一次。
let loaded = false;
async function loadOnce() {
  if (loaded) return;
  loaded = true;
  await load();
  await autoCheck();
}

// 启动时**自动检测一次**（用户 2026-10-03：「要启动时自动检测程序更新」）。
// use_cache=True ⇒ 有缓存就不重复打网络，离线时静默。
async function autoCheck() {
  try {
    const r = await call("check_app_update", true);
    if (r && r.update_available) {
      latest.value = String(r.latest || "");
      note.value = `发现新版本 v${r.latest}`;
    }
  } catch (e) { /* 离线/失败都保持安静 */ }
}

watch(() => store.ready, (ready) => { if (ready) loadOnce(); }, { immediate: true });
onStateRefreshed(() => { if (store.ready) loadOnce(); });

async function checkNow() {
  busy.value = true;
  note.value = "正在检查…";
  try {
    // use_cache=False：用户主动点的时候要真的打一次网络
    const r = await call("check_app_update", false);
    if (r && r.update_available) {
      latest.value = String(r.latest || "");
      note.value = `发现新版本 v${r.latest}`;
      showToast(`发现新版本 v${r.latest}`, "info");
    } else if (r && r.error) {
      note.value = `检查失败：${r.error}`;
    } else {
      note.value = "已是最新";
      showToast(`已是最新（v${(r && r.current) || current.value}）`, "success");
    }
  } catch (e) {
    note.value = "检查失败";
  } finally {
    busy.value = false;
  }
}

async function startUpdate() {
  if (busy.value) return;
  busy.value = true;             // 弹确认框期间就置忙，避免连点开出多个确认框、重复触发更新
  const ok = await showModalDialog({
    title: latest.value ? `更新到 v${latest.value}？` : "重启以完成更新？",
    message: latest.value
      ? `会下载新版本并替换当前程序，然后自动重启。\n你的 Mod 库、配置与备份都不会动。`
      : `更新包已经下载好了，现在重启程序来装上它。`,
    okText: latest.value ? "下载并更新" : "重启并安装", cancelText: "稍后",
  });
  if (!ok) { busy.value = false; return; }
  note.value = "正在处理…";
  try {
    if (pending.value) {
      await call("apply_app_update");
    } else {
      await call("start_app_update");
      // ⚠️ **跳到「下载」页**（2026-10-07 改：以前跳「依赖」页，而依赖页现在只留组件
      //    状态与开关，进度/速度/日志统一在下载页）。**不锁页**：不做任何拦截，
      //    用户随时可以自己切走，下载与下面的轮询都在后台继续（徽章上也一直显示进度）。
      store.tab = "downloads";
      // 下载是后台线程 —— 起一个 1 秒轮询，把百分比和速度显示出来，别让用户干等
      dlPercent.value = 0;
      dlSpeed.value = 0;
      stopPolling();
      dlTimer.value = setInterval(pollDownload, 1000);
      pollDownload();
    }
  } catch (e) {
    /* call() 已经弹过窗 */
  } finally {
    busy.value = false;
  }
}

function onClick() {
  if (busy.value) return;
  if (pending.value || latest.value) startUpdate();
  else checkNow();
}

</script>

<template>
  <button class="w-full flex items-center gap-2.5 px-3 py-2 rounded text-sm text-left"
          :style="(latest || pending)
            ? { background: 'var(--accent-soft)', color: 'var(--accent)', fontWeight: 500 }
            : { color: 'var(--text-muted)' }"
          :title="note || '点击检查程序更新'"
          @click="onClick">
    <component :is="icon()" :size="16" class="shrink-0" />
    <span class="min-w-0 truncate">
      <!-- ⚠️ **下载中要看到百分比**（2026-10-03 用户：「安装日志不动、没速度、条在走」）——
           原来下载期间这里还是显示 "v当前 → v新版"，看不出正在下多少。 -->
      <template v-if="dlTimer">下载中 {{ dlPercent }}%<template v-if="dlSpeed > 0"> · {{ humanSize(dlSpeed) }}/s</template></template>
      <template v-else-if="pending">重启以完成更新</template>
      <template v-else-if="latest">v{{ current }} → v{{ latest }}</template>
      <!-- 拿不到版本号时说人话（评审：「版本 未知」像内部状态，不像可点的入口） -->
      <template v-else>{{ current ? "版本 v" + current : "检查程序更新" }}</template>
    </span>
  </button>
  <!-- 下载中的细进度条（压在徽章底部）：让"还在动"这件事一眼可见 -->
  <div v-if="dlTimer" class="h-0.5 rounded-full overflow-hidden mx-1"
       style="background: var(--surface-2)">
    <div class="h-full transition-all" :style="{ width: dlPercent + '%', background: 'var(--accent)' }"></div>
  </div>
</template>
