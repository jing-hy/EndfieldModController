<script setup>
// 自更新入口（旧版是顶栏那个 `v0.9.x` 徽标；Vue 换皮时漏掉了，2026-10-03 用户发现）。
// 位置按用户要求：**左侧导航栏下面、主题色上面**。
//
// 三种状态：
//   ① 普通       —— 显示当前版本，点了主动检查一次
//   ② 有新版     —— `v当前 → v新版` + 高亮，点了下载并更新
//   ③ 已下载待装 —— 「重启以完成更新」，点了立刻应用（用户选过"稍后"会停在这）
import { ref, onMounted } from "vue";
import { call } from "../lib/bridge.js";
import { store } from "../store.js";
import { showAlert, showModalDialog, showToast } from "../lib/dialog.js";
import { Download, RefreshCw, CheckCircle2 } from "lucide-vue-next";

const current = ref("");
const latest = ref("");
const pending = ref(false);
const busy = ref(false);
const note = ref("");

function icon() {
  if (pending.value) return RefreshCw;
  if (latest.value) return Download;
  return CheckCircle2;
}

async function load() {
  try {
    const info = await call("get_app_info");
    if (info && info.version) current.value = String(info.version);
  } catch (e) { /* 拿不到就留空 */ }
  try {
    const p = await call("pending_update");
    pending.value = !!(p && p.pending);
  } catch (e) { /* 忽略 */ }
}

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
    if (pending.value) await call("apply_app_update");
    else await call("start_app_update");
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

onMounted(async () => {
  await load();
  // 静默检查一次（有缓存，不会每次都打网络）—— 与旧版行为一致
  try {
    const r = await call("check_app_update", true);
    if (r && r.update_available) {
      latest.value = String(r.latest || "");
      note.value = `发现新版本 v${r.latest}`;
    }
  } catch (e) { /* 离线时保持安静 */ }
});
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
      <template v-if="pending">重启以完成更新</template>
      <template v-else-if="latest">v{{ current }} → v{{ latest }}</template>
      <!-- 拿不到版本号时说人话（评审：「版本 未知」像内部状态，不像可点的入口） -->
      <template v-else>{{ current ? "版本 v" + current : "检查程序更新" }}</template>
    </span>
  </button>
</template>
