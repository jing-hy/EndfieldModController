<script setup>
// 依赖页（旧 #tab-dependencies）：组件状态 + 下载进度 + 日志 + 已装清单。
// ⚠️ 日志框是**纯黑**的（.log-box 在 tokens.css 里，且 user-select: text 保证可复制）。
import { ref, computed, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import { store, refreshState } from "../store.js";
import { loadSettings } from "../lib/settings.js";
import { showToast, showAlert, showModalDialog } from "../lib/dialog.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";

const items = ref([]);
const running = ref(false);
const checked = ref(false);   // 是否至少查过一次（区分"未检查"和"已就绪"）
// ⚠️ 日志内容放 **store**（切页不丢）—— 见 store.js 里的说明
const logLines = computed({
  get: () => (store.depLogLines.length ? store.depLogLines
    : ["等待开始…（这里会显示下载线路尝试、断点续传、组件安装等详细过程）"]),
  set: (v) => { store.depLogLines = v; },
});
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
const modDlActive = ref(false);        // 是否有 Mod 下载在跑（用来联动进度条与速度）
const modDlHasRecord = ref(false);      // 有没有下载任务记录（决定是否显示「继续 / 清除记录」）
// 「香蕉网高速下载」的显示状态（2026-10-03）：并发连接数 / 是否在加速 / 当前策略
const mdThreads = ref(0);
const mdAccelerating = ref(false);
const mdPolicy = ref("");

// ⚠️ **Mod 下载的控制**（2026-10-03 补回归）。
// 0.9.5 有「暂停 / 终止 / 继续 / 清除记录」四个按钮（旧 app.js 的 renderModDownload +
// bindDownloadListClicks），换代到 Vue 后全丢了 —— 后端 `pause_mod_downloads` /
// `cancel_mod_downloads` / `resume_mod_downloads` / `clear_mod_downloads` 四个方法一直健在，
// 而现前端 grep 这四个名字**全 0 命中** ⇒ 下载太慢或下错了**没法停**。
async function modDlControl(act) {
  const map = {
    pause:  ["pause_mod_downloads",  "已暂停（断点保留，点「继续」可接着下）"],
    resume: ["resume_mod_downloads", "已继续下载"],
    cancel: ["cancel_mod_downloads", "已终止（半成品会清掉）"],
    clear:  ["clear_mod_downloads",  "已清除下载记录"],
  };
  const entry = map[act];
  if (!entry) return;
  if (act === "cancel") {
    const ok = await showModalDialog({
      title: "终止下载",
      message: "会停下所有 Mod 下载任务，**已下完的部分会被清掉**。\n\n确定终止吗？\n（只是想暂存进度就选「暂停」，那会保留断点。）",
      okText: "终止并清掉半成品", cancelText: "取消", focusCancel: true,
    });
    if (!ok) return;
  }
  try {
    const r = await call(entry[0]);
    if (r && r.ok === false) { showToast(String(r.message || "操作失败"), "danger"); return; }
    showToast(entry[1], act === "cancel" ? "warning" : "success");
  } catch (e) {
    showToast(String((e && e.message) || "操作失败"), "danger");
    return;
  }
  await sleep(300);          // 给后端一点时间落状态
  await pollProgress();      // 立刻刷新一次，按钮与进度条跟着变
}

// 「检查并补齐」——**要 await、要刷新、要有反馈**（原来模板里裸调 call，结果全丢）
async function checkAndComplete() {
  try {
    const r = await call("ensure_initialized");
    await refreshState();
    await refresh();
    if (r && r.ok === false) {
      showToast(String(r.message || "检查失败"), "danger");
    } else {
      showToast("已检查并补齐缺失组件", "success");
    }
  } catch (e) {
    showToast(String((e && e.message) || "检查失败"), "danger");
  }
}

const modDlMarks = new Map();          // 每条任务上次记下的状态与百分比台阶（避免刷屏）
// ⚠️ 准备阶段的提示（读取香蕉网信息要 18~51 秒，这期间没有字节在动）
const prepLabel = ref("");
const speedText = computed(() => {
  if (speedBps.value > 0) return humanSize(speedBps.value) + "/s";
  return prepLabel.value || "—";
});
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

let wasRunning = false;
// Mod 下载的"上一轮是否活跃"——用来捕捉"刚下完"那一刻只弹一次窗
let wasModDlActive = false;      // 上一轮是否在跑（用来捕捉"刚跑完"这个瞬间）

async function pollProgress() {
  try {
    const p = await call("get_dependency_progress");
    if (!p) return;
    const nowRunning = !!p.running;
    running.value = nowRunning;
    // 优先用**字节口径**的进度（跟着实际大小走）；拿不到才退回项数口径。
    // 用户 2026-10-03：「进度条不要一卡一卡的，应该跟着实际大小走」——
    // 项数口径下 138 MB 的大包只算 1 项，进度条会长时间停着不动。
    if (typeof p.byte_percent === "number" && p.expected_bytes > 0) percent.value = p.byte_percent;
    else if (typeof p.percent === "number") percent.value = p.percent;
    // ⚠️ 不能无脑 `logLines.value = p.log`：Mod 下载那些行是**追加**进同一个日志框的，
    // 整份替换会把它们冲掉（用户要的是"向下滚"）。这里只在**组件安装日志真的变了**
    // 或者**之前没有过组件日志**时替换，并把已有的 Mod 下载行接在后面。
    if (Array.isArray(p.log) && p.log.length) {
      const base = p.log;
      const tail = logLines.value.filter((ln) => String(ln).startsWith("[Mod 下载]"));
      const merged = tail.length ? [...base, ...tail] : base;
      const changed = merged.length !== logLines.value.length
        || merged.some((ln, i) => ln !== logLines.value[i]);
      if (changed) logLines.value = merged;
    }
    speedBps.value = Number(p.speed_bps || 0);   // 下载实时速度（第 4 个卡片）

    // ⚠️ Mod 下载（「下载 Mod」卡片）也在这里显示 —— 用户 2026-10-03 明确了形态：
    // 「mod下载**不是日志式的向下滚**，而是同一条」**说反了**，随后纠正为
    // 「现在是同一条原地更新，**我需要向下滚**」⇒ 要的是**日志式、不断向下追加**。
    // 所以这里不是"每轮把整块文本替换掉"，而是**把新的进展追加到日志框末尾并滚到底**。
    // 同时把它的总进度/速度接到上面的进度条与「下载速度」卡片上（用户：「没联动进度条和下载速度」）。
    try {
      const md = await call("mod_download_progress");
      const items = (md && md.items) || [];
      // ⚠️ **只要有任务就算"活跃"**（2026-10-03 用户：「速度一直是横线，进度条也没开始，
      // 文字也是未开始」）。原先这里是 `items.length > 0 && !md.done` ——
      // 任务刚起来时后端还在「读取香蕉网信息」（要 18~51 秒：拿文件列表、封面、算真实直链），
      // 这段时间 `done` 还没置、但进度/速度全是 0，前端就什么都不显示 ⇒
      // 用户看到的是"未开始 + 速度横线"，以为程序没动。
      // 现在：**有任务就活跃**，并把这个阶段如实显示出来。
      modDlActive.value = items.length > 0 && !md.done;
      modDlHasRecord.value = items.length > 0 || !!md.done;
      if (items.length && !md.done) {
        const prepping = items.filter((it) => !Number(it.size) && !Number(it.received));
        if (prepping.length) {
          const st = String(prepping[0].status || "准备中");
          progressText.value = `Mod 下载：${st}…（${prepping.length} 个）`;
          if (!speedBps.value) prepLabel.value = "探测中…";
        }
      }
      if (items.length) {
        for (const it of items) {
          const pct = it.size ? Math.floor((it.received / it.size) * 100) : -1;
          const key = String(it.url || it.name || "");
          const prev = modDlMarks.get(key) || { status: "", step: -1 };
          // 只在"状态变了"或"进度跨过 10% 台阶"时追加一行 —— 否则每秒一条会把日志淹掉
          const step = pct >= 0 ? Math.floor(pct / 10) : -1;
          if (it.status !== prev.status || step > prev.step) {
            modDlMarks.set(key, { status: String(it.status || ""), step });
            const size = it.size
              ? ` (${(it.received / 1048576).toFixed(1)}/${(it.size / 1048576).toFixed(1)} MB)`
              : "";
            const msg = it.message ? ` — ${it.message}` : "";
            logLines.value = [...logLines.value, `[Mod 下载] ${it.status || "下载中"}${size}  ${it.name || it.url}${msg}`];
          }
        }
      }
      // 联动：进度条与「下载速度」卡片 —— Mod 下载期间用它的数据
      // ⚠️⚠️ **速度和进度必须分开判断**（2026-10-03 用户报了两次「下载速度和进度条还是没同步」）。
      // 原实现是 `if (modDlActive && md.total_bytes) { …进度…; …速度… }` ——
      // 而 `total_bytes` 是"各任务 size 之和"，**服务器没给 Content-Length 时它就是 0**
      //（香蕉网部分直链如此），于是整块被跳过：进度条不动，**速度也一起不更新**；
      // 而上面那行已经把 `speedBps` 设成了依赖下载的 0 ⇒ 速度卡片恒显示「—」。
      if (modDlActive.value) {
        if (md.total_bytes > 0) {
          percent.value = Math.min(99, Math.round((md.done_bytes / md.total_bytes) * 100));
          progressText.value = `Mod 下载 ${(md.done_bytes / 1048576).toFixed(1)}/${(md.total_bytes / 1048576).toFixed(1)} MB`;
        } else if (items.length) {
          // 总大小未知：用各任务自身百分比的平均兜底，别让进度条死住
          const known = items.filter((it) => Number(it.size) > 0);
          if (known.length) {
            const avg = known.reduce((s, it) => s + Number(it.received) / Number(it.size), 0) / known.length;
            percent.value = Math.min(99, Math.round(avg * 100));
          } else {
            const doneCount = items.filter((it) => /完成|已入库/.test(String(it.status || ""))).length;
            percent.value = Math.min(99, Math.round((doneCount / items.length) * 100));
          }
          progressText.value = `Mod 下载 ${(md.done_bytes / 1048576).toFixed(1)} MB（总大小未知）`;
        }
        // 速度是**独立信号**，不依赖是否知道总大小 —— 无条件接上
        const spd = Number(md.speed_bps || 0);
        if (spd > 0) speedBps.value = spd;
        else if (items.length) {
          const sum = items.reduce((s, it) => s + Number(it.speed_bps || 0), 0);
          if (sum > 0) speedBps.value = sum;
        }

        // ⚠️ **「香蕉网高速下载」的状态**（2026-10-03 用户：「香蕉网高速下载逻辑也加进去」）。
        // 只让用户看到"下载多少 MB/s"是不够的 —— 他还需要知道**现在是不是在并发加速**
        // （他 2026-10-03 报的正是"为什么下载这么慢"）。这里如实显示连接数与策略来源：
        // 并发跑起来就是「⚡ 高速下载（N 连接）」；被设置关掉就提示去哪开。
        mdThreads.value = Number(md.threads || 0);
        mdAccelerating.value = !!md.accelerating;
        mdPolicy.value = String(md.policy || "");
      }

      // ⚠️ **下载完成的弹窗**（2026-10-03 用户：「下载完 mod 应该和拖入 zip 一样有个弹窗」）。
      // 形态**照抄拖入 zip 那套**（`importMod.js` 用 `showAlert("导入 Mod", …)`），
      // 文案也保持一致：识别到角色就报角色，没识别出来就提示去「⋯ → 更换归属」。
      // 判定用**边沿**：上一轮还在下、这一轮 `done` ⇒ 只在"刚下完"那一刻弹一次。
      // ⚠️ 条件里**不要**再要求 `items.length`（2026-10-03 用户：「下载的已入库还是没有弹窗」）：
      // 后端跑完会把 `done` 置真，但 `items` 若干轮之后可能被下一次任务替换/清空，
      // 那一刻正好被轮询撞上就永远不弹。只在"上一轮还在下、这一轮 done"时弹，就够了。
      if (wasModDlActive && md && md.done) {
        // ⚠️ **下载完要重新扫描并刷新界面**（2026-10-03 用户：「下载完 mod 不会自动刷新
        // mod 列表」）。原先只有"组件安装完"会刷新（下面那段 running→false 的逻辑），
        // Mod 下载走的是**另一条任务链**，跑完没人通知界面 ⇒ 服装/辅助页看不到新下的 Mod。
        try {
          await call("scan");
          await refreshState();
        } catch (e) { /* 刷不动不影响弹窗 */ }
        const okItems = items.filter((it) => !/失败/.test(String(it.status || "")));
        const badItems = items.filter((it) => /失败/.test(String(it.status || "")));
        if (okItems.length) {
          const lines = okItems.map((it) => `· ${it.name || it.url}${it.group ? ` —— 识别为「${it.group}」` : ""}`);
          await showAlert(
            "Mod 下载完成",
            `已下载并入库 ${okItems.length} 个（列表已刷新）：\n${lines.join("\n")}\n\n` +
            (badItems.length ? `另有 ${badItems.length} 个失败，可在本页重试。\n\n` : "") +
            "如果某个没识别出角色，去「服装 Mod / 辅助 Mod」页点它的「⋯ → 更换归属」设定。",
          );
        } else if (badItems.length) {
          await showAlert("Mod 下载失败",
            badItems.map((it) => `· ${it.name || it.url}：${it.message || it.status}`).join("\n"));
        }
      }
      wasModDlActive = modDlActive.value;
    } catch (e) { /* 没有 Mod 下载任务很正常 */ }
    // ⚠️ **组件安装的进度文字不能覆盖 Mod 下载的**（2026-10-03 用户：
    //     「进度条下面未开始的字样没有联动」）。
    // 上面 Mod 分支设过 `Mod 下载 x/y MB`，而这一行原先**无条件**把它冲成
    // `p.message || ""`（依赖任务没在跑时就是空串）⇒ 模板的 `|| "尚未开始"` 兜底生效，
    // 于是下载时进度文字永远显示「尚未开始」。
    const depText = p.total
      ? `第 ${p.current}/${p.total} 项` + (p.computed_bytes ? ` · ${(p.computed_bytes / 1048576).toFixed(1)} MB` : "")
      : (p.message || "");
    if (depText) progressText.value = depText;
    else if (!modDlActive.value) progressText.value = "";

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
      <!-- ⚠️ 原来这里是模板里裸调 `call('ensure_initialized')`（2026-10-03 修）：
           连 `await` 都没有 ⇒ 结果丢弃、页面也不刷新、失败也看不到。 -->
      <Btn @click="checkAndComplete">检查并补齐</Btn>
      <Btn id="dep-update-all-btn" variant="primary" @click="start">安装缺失依赖</Btn>

      <!-- ⚠️ **Mod 下载的控制按钮**（2026-10-03 补回归）。
           0.9.5 有 暂停 / 终止 / 继续 / 清除记录 四个按钮，换代到 Vue 后**全没了**
           （后端四个方法一直健在，现前端 grep 全 0 命中）——
           下载链接下错、或者线路太慢想停下时，用户**没有任何办法停**。
           展示沿用现有 Btn（size="sm"），只在有任务/有记录时出现。 -->
      <template v-if="modDlActive">
        <Btn size="sm" @click="modDlControl('pause')">暂停</Btn>
        <Btn size="sm" variant="danger" @click="modDlControl('cancel')">终止</Btn>
      </template>
      <Btn v-else-if="modDlHasRecord" size="sm" @click="modDlControl('resume')">继续</Btn>
      <Btn v-if="modDlHasRecord" size="sm" @click="modDlControl('clear')">清除记录</Btn>
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
        <!-- ⚠️ **「香蕉网高速下载」的状态**（2026-10-03 用户：「香蕉网高速下载逻辑也加进去」）。
             只显示 MB/s 不够 —— 用户还要知道"现在到底有没有在并发加速"，
             否则"下载慢"这件事他没法判断是线路问题、还是加速没开。 -->
        <div class="text-xs mt-0.5" style="color: var(--text-muted)">
          下载速度<template v-if="mdAccelerating">　⚡ 高速下载（{{ mdThreads }} 连接）</template>
          <template v-else-if="mdPolicy === 'never'">　加速已关闭（设置 → 下载加速）</template>
        </div>
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
          <div v-if="logLines.length" ref="logBox" class="log-box" style="max-height: 420px; border-radius: 0">{{ logLines.join("\n") }}</div>
          <div v-else class="log-empty" style="min-height: 52px; text-align: center">
            尚未开始。点「安装缺失依赖」后，这里会显示下载线路与安装过程。
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
