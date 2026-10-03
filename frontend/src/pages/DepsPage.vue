<script setup>
// 依赖页（旧 #tab-dependencies）：组件状态 + 下载进度 + 日志 + 已装清单。
// ⚠️ 日志框是**纯黑**的（.log-box 在 tokens.css 里，且 user-select: text 保证可复制）。
import { ref, computed, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import { store, refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";

const items = ref([]);
const running = ref(false);
const checked = ref(false);   // 是否至少查过一次（区分"未检查"和"已就绪"）
const logLines = ref(["等待开始…（这里会显示下载线路尝试、断点续传、组件安装等详细过程）"]);
const status = ref("");
const percent = ref(0);
const progressText = ref("");   // 空 = 尚未开始，由 {{ ... || "尚未开始" }} 兜底
let timer = null;

// 真实结构：get_state().dependency_report = { required:[], manifest:{key:{display,status,version,install_dir,present,needed}}, unknown:[] }
const deps = computed(() => {
  const m = (store.state.dependency_report || {}).manifest || {};
  return Object.entries(m).map(([key, v]) => ({ key, ...v }));
});
const required = computed(() => (store.state.dependency_report || {}).required || []);
const okCount = computed(() => deps.value.filter((d) => d.status === "已安装").length);
const missingCount = computed(() => deps.value.filter((d) => d.status === "缺失").length);
// ⚠️ 原来的 `tone(state)` 判的是 `"ok"` / `"missing"`，而后端 `status` 实际是**中文**
// （`已安装` / `已就位` / `已是最新` / `缺失`）⇒ 永远落到 muted（灰），缺了的组件也看不出来。
// 用户 2026-10-03：「组件确实要标红，正常标绿」。改用后端给的**真布尔** `present` 判断，
// 比匹配中文字符串可靠（status 是给人看的，present 是给机器判的）。
function tone(d) {
  return d && d.present ? "success" : "danger";
}
function rowColor(d) {
  return d && d.present ? "var(--success, #2e7d32)" : "var(--danger, #c0392b)";
}

// 下载实时速度：后端在 byte_progress 里采样并平滑过；不在下载时是 0 ⇒ 显示 —（不留假数字）
const speedBps = ref(0);      // 由 pollProgress 从 get_dependency_progress 里取
const modDlLines = ref([]);   // 「下载 Mod」那条链路的进度（拼成日志行显示）
const speedText = computed(() => (speedBps.value > 0 ? humanSize(speedBps.value) + "/s" : "—"));
function humanSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n.toFixed(0) + " B";
}

const progressLabel = computed(() => {  // 评审指出：摘要写「已就绪」、进度写「尚未开始」，两个状态互相打架 ——
  // 这里统一成**一次流程**的状态，并且明确"还没检查过"这一档。
  if (running.value) return "进行中";
  if (!checked.value) return "未检查";
  if (missingCount.value) return "待补齐";
  return "全部就位";
});

async function refresh() {
  try {
    await refreshState();
    checked.value = true;
    loadSettings();
    const total = deps.value.length;
    const ok = deps.value.filter((d) => d.status === "已安装").length;
    status.value = total ? `${ok}/${total} 个组件已就位` : "";
  } catch (e) { /* call 已弹窗 */ }
}

let wasRunning = false;      // 上一轮是否在跑（用来捕捉"刚跑完"这个瞬间）

async function pollProgress() {
  try {
    const p = await call("get_dependency_progress");
    if (!p) return;
    const nowRunning = !!p.running;
    running.value = nowRunning;
    if (typeof p.percent === "number") percent.value = p.percent;
    if (Array.isArray(p.log) && p.log.length) logLines.value = p.log;
    speedBps.value = Number(p.speed_bps || 0);   // 下载实时速度（第 4 个卡片）

    // ⚠️ Mod 下载（「下载 Mod」卡片）也在这里显示：用户 2026-10-03 要求
    // 「mod下载应该跳转到依赖页下载，过程中显示日志那些」。
    // 它是独立的任务（`_mod_dl`），跟组件下载不是同一份进度，所以这里单独拉一次、
    // 把每条的状态拼成日志行贴到日志框顶部，失败了也看得到原因。
    try {
      const md = await call("mod_download_progress");
      const items = (md && md.items) || [];
      if (items.length) {
        const lines = items.map((it) => {
          const pct = it.size ? ` ${Math.round((it.received / it.size) * 100)}%` : "";
          const size = it.size ? ` (${(it.received / 1048576).toFixed(1)}/${(it.size / 1048576).toFixed(1)} MB)` : "";
          const msg = it.message ? ` — ${it.message}` : "";
          return `[Mod 下载] ${it.status || "下载中"}${pct}${size}  ${it.name || it.url}${msg}`;
        });
        modDlLines.value = lines;
      } else {
        modDlLines.value = [];
      }
    } catch (e) { /* 没有 Mod 下载任务很正常 */ }
    progressText.value = p.total ? `${p.current}/${p.total}` : (p.message || "");

    // ⚠️ 用户 2026-10-03：「安装完成没动态，不会自动刷新组件状态，而且安装完还是待补齐」——
    // 这里原来**只更新进度条**，从不在跑完时刷新组件清单，于是 `deps` / `missingCount`
    // 一直是开始前的旧数据：装完了仍显示"待补齐"、Badge 也还是旧的。
    // 捕捉 running: true → false 的那一刻：拉一次最新状态 + 给一条完成提示。
    if (wasRunning && !nowRunning) {
      await refresh();
      // 后端没有顶层 failed/missing，只有 results（每项 status ∈
      // up_to_date|updated|downloaded|missing|error|skipped）—— 这里自己归类。
      const results = Array.isArray(p.results) ? p.results : [];
      const failed = results.filter((r) => String(r && r.status) === "error").length;
      const missing = results.filter((r) => String(r && r.status) === "missing").length;
      const message = String(p.message || "");
      if (failed > 0) {
        showToast(`安装结束，但有 ${failed} 项失败 —— 详情见右侧安装日志`, "danger");
      } else if (missing > 0) {
        showToast(`安装结束，仍有 ${missing} 项缺失 —— 详情见右侧安装日志`, "warn");
      } else if (message.startsWith("失败")) {
        showToast(`安装失败：${message}`, "danger");
      } else {
        showToast("依赖安装/更新完成", "success");
      }
    }
    wasRunning = nowRunning;
  } catch (e) { /* 忽略轮询错误 */ }
}

async function start() {
  running.value = true;
  wasRunning = true;
  try { await call("start_full_update"); } catch (e) { running.value = false; wasRunning = false; return; }
  status.value = "已开始自动安装/更新…";
  await refresh();
}

onMounted(() => {
  refresh();
  timer = setInterval(pollProgress, 1200);
  // 「依赖清空并重新下载」在设置页清完会置这个标志并跳过来 —— 这里自动开跑，
  // 用户不用再找按钮点一次（用户 2026-10-03 要求：「清空完…然后跳转到依赖页走正常
  // 下载流程，包括那些日志什么的」）。日志靠下面的 pollProgress 轮询同一个后端进度。
  if (store.autoStartDeps) {
    store.autoStartDeps = false;
    logLines.value = ["已清空 runtime 与 assets，开始重新下载依赖…"];
    start();
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });

// 日志框自动滚到底（不抢鼠标、没新内容不动）
const logBox = ref(null);
useLogAutoScroll(logBox, () => logLines.value);
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-2">
      <Btn @click="refresh">重新扫描</Btn>
      <Btn @click="call('ensure_initialized')">检查并补齐</Btn>
      <Btn id="dep-update-all-btn" variant="primary" @click="start">安装缺失依赖</Btn>
    </div>

    <!-- 两列（GPT-6 Astra 评审：摘要/进度/日志全占首屏，真正要看的组件列表起点太低）：
         左 = 摘要 + 进度 + 组件列表（要看的）；右 = 安装日志（要盯的，滚动时吸顶）。 -->
    <div class="two-col grid gap-4">
      <div class="space-y-4 min-w-0">

    <!-- 状态摘要：把"现在到底什么情况"用三个数字说清楚（评审：原来只有 0/0 和一行日志） -->
    <div class="grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))">
      <div class="card"><div class="card-body">
        <div class="text-xl font-semibold">{{ okCount }}</div>
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">已就位组件</div>
      </div></div>
      <div class="card"><div class="card-body">
        <div class="text-xl font-semibold">{{ missingCount }}</div>
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">缺失组件</div>
      </div></div>
      <div class="card"><div class="card-body">
        <div class="text-xl font-semibold">{{ progressLabel }}</div>
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">当前状态</div>
      </div></div>
      <!-- 第 4 个：下载实时速度（用户 2026-10-03：「不是上面三个卡片还有一个空位吗，
           可以把下载实时速度开个卡片放那里」）。不在下载时显示 —，不留一个假数字。 -->
      <div class="card"><div class="card-body">
        <div class="text-xl font-semibold">{{ speedText }}</div>
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">下载速度</div>
      </div></div>
    </div>

    <div>
      <div class="h-1.5 rounded-full overflow-hidden" style="background: var(--surface-2); border: 1px solid var(--border)">
        <div class="h-full transition-all" :style="{ width: percent + '%', background: 'var(--accent)' }"></div>
      </div>
      <div class="text-xs mt-1.5" style="color: var(--text-muted)">{{ progressText || "尚未开始" }}</div>
    </div>

    <Card v-if="deps.length" title="组件状态">
      <div class="divide-y" style="border-color: var(--border)">
        <div v-for="d in deps" :key="d.key" class="py-2.5 flex items-center justify-between gap-4"
             :style="{ borderLeft: `3px solid ${rowColor(d)}`, paddingLeft: '10px' }">
          <div class="min-w-0">
            <div class="font-medium truncate">{{ d.display || d.key }}</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">{{ d.version || "" }}</div>
          </div>
          <Badge :tone="tone(d)">{{ d.status || "未知" }}</Badge>
        </div>
      </div>
    </Card>

    <Card v-if="required.length" title="被引用的依赖名">
      <div class="flex flex-wrap gap-1.5">
        <Badge v-for="r in required" :key="r" tone="muted">{{ r }}</Badge>
      </div>
    </Card>
      </div>

      <!-- 右栏：安装日志（滚动时吸顶） -->
      <div class="min-w-0" style="align-self: start; position: sticky; top: 12px">
        <div class="log-card">
          <div class="log-card-head">
            <span>安装日志</span>
            <span class="text-xs" style="color: var(--text-muted); font-weight: 400">
              {{ logLines.length > 1 ? logLines.length + " 行" : "尚无日志" }}
            </span>
          </div>
          <div v-if="logLines.length || modDlLines.length" ref="logBox" class="log-box" style="max-height: 420px; border-radius: 0">{{ modDlLines.length ? modDlLines.join("\n") + "\n" + logLines.join("\n") : logLines.join("\n") }}</div>
          <div v-else class="log-empty" style="min-height: 52px; text-align: center">
            尚未开始。点「安装缺失依赖」后，这里会显示下载线路与安装过程。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
