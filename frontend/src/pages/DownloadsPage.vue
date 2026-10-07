<script setup>
// 下载中心（2026-10-07 新增，侧栏「下载」页）。
//
// 用户原话：「把下载从**依赖里面抽出来**，之前是所有下载跳转依赖的现在都跳转下载，
// 依赖也跳转下载，**下载可以后台进行，可以追加任务**，看商城不用下一个就跳转一次，
// 但是要有动态」。
//
// 这一页是**唯一**看下载进度的地方：Mod 队列 + 依赖/组件任务都在这里；
// 依赖页因此瘦身成"组件状态 + 开关 + 更新入口"（点更新即跳本页）。
//
// ⚠️ 两条设计约束（都是踩过坑之后定的）：
// ① **数据只来自后端快照**（`downloads_snapshot`），前端**不再自己累积日志** ——
//    依赖页原先靠"状态变化时追加一行"攒日志，组件一销毁就没了
//    （用户 2026-10-03 实测：「下载的时候切到其他页面，再切回依赖，就会清空日志」）。
//    这里直接呈现后端 `_dep_task["log"]`：权威、可重放、与组件生命周期无关。
// ② **进度一律走字节口径**（`byte_percent`），拿不到才退回项数口径 ——
//    项数口径下 138 MB 的资产包只算 1 项，进度条会长时间不动（用户 2026-10-03 报过
//    「进度条不要一卡一卡的，应该跟着实际大小走」）。
import { ref, computed, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { store } from "../store.js";
import { humanSize, sleep } from "../lib/util.js";
import { showModalDialog, showToast } from "../lib/dialog.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Badge from "../components/ui/Badge.vue";
import ProgressBar from "../components/ui/ProgressBar.vue";
import ModDownloadCard from "../components/ModDownloadCard.vue";

const tasks = ref([]);
const activeCount = ref(0);
const totalSpeed = ref(0);
let timer = null;

const modTask = computed(() => tasks.value.find((t) => t.kind === "mods") || null);
const depTask = computed(() => tasks.value.find((t) => t.kind === "deps") || null);
const modItems = computed(() => (modTask.value && modTask.value.items) || []);
const modActive = computed(() => !!(modTask.value && modTask.value.running));
const logLines = computed(() => (depTask.value && depTask.value.log) || []);
const counts = computed(() => (modTask.value && modTask.value.counts) || {});
// 有"内容"才画卡片：干过活的记录（哪怕已结束）也留着，方便回看结果
const hasMods = computed(() => modItems.value.length > 0);
const hasDeps = computed(() => !!depTask.value);
const nothing = computed(() => !hasMods.value && !hasDeps.value);

// 状态徽标色调 —— 与后端 `moddl.summarize()` 的口径对齐
const TONES = {
  "已入库": "success", "下载中": "accent", "读取香蕉网信息": "accent", "解压中": "accent",
  "等待中": "muted", "需手动解压": "warn", "已暂停": "warn", "已终止": "muted", "失败": "danger",
};

function toneOf(status) {
  return TONES[String(status || "")] || "muted";
}

function speedText(bps) {
  const value = Number(bps || 0);
  return value > 0 ? humanSize(value) + "/s" : "—";
}

function percentOf(task) {
  if (!task) return 0;
  // 字节口径优先（跟着实际大小走）；任务完成时后端已把 percent 抬到 100
  return Number(task.byte_percent || task.percent || 0);
}

async function refresh() {
  try {
    const result = await call("downloads_snapshot");
    if (!result || result.ok === false) return;
    tasks.value = result.tasks || [];
    activeCount.value = Number(result.active || 0);
    totalSpeed.value = Number(result.speed_bps || 0);
    // 侧栏徽标读同一份真源（App.vue 每 2 秒也在刷；这里顺手对齐，切换更跟手）
    store.activeDownloads = activeCount.value;
  } catch (e) { /* 轮询失败保持上一次的显示，不打扰用户 */ }
}

// ── 任务控制（与后端 `downloads_*` 一一对应；不支持的类型后端会如实拒绝）─────────
const METHODS = {
  pause: "downloads_pause", resume: "downloads_resume",
  cancel: "downloads_cancel", clear: "downloads_clear",
};
const DONE_TEXT = {
  pause: "已暂停（断点保留，点「继续」可接着下）",
  resume: "已继续下载",
  cancel: "已终止（半成品已清掉）",
  clear: "已清除下载记录",
};

async function control(act) {
  const method = METHODS[act];
  if (!method) return;
  if (act === "cancel") {
    // 破坏性动作：按钮自解释 + 默认聚焦安全项（项目既定规矩）
    const ok = await showModalDialog({
      title: "终止下载",
      message: "会停下所有下载任务，**已下完的部分会被清掉**。\n\n确定终止吗？\n"
             + "（只是想暂存进度就选「暂停」，那会保留断点。）",
      okText: "终止并清掉半成品", cancelText: "继续下载", focusCancel: true,
    });
    if (!ok) return;
  }
  try {
    const result = await call(method, "");
    if (result && result.ok === false) {
      showToast(String(result.message || "操作失败"), "danger");
      return;
    }
    if (result && result.resumed === 0 && act === "resume") {
      showToast("没有可继续的任务", "info");
    } else {
      showToast(DONE_TEXT[act] || "已处理", act === "cancel" ? "warning" : "success");
    }
  } catch (e) {
    return;                                  // call 已经弹过错误窗
  }
  await sleep(250);                          // 给后端一点时间落状态
  await refresh();
}

async function openDir() {
  const result = await call("open_download_dir");
  if (result && result.ok === false) showToast(String(result.message || "打不开下载目录"), "danger");
}

// 依赖/组件下载：没有暂停语义（`ensure_all` 是一条顺下来的流程），所以这里只负责"开跑"
async function startDeps(note = "") {
  if (depTask.value && depTask.value.running) return;      // 已经在跑，别重复触发
  try {
    await call("start_full_update");
    if (note) showToast(note, "info");
  } catch (e) {
    return;
  }
  await sleep(300);
  await refresh();
}

onMounted(async () => {
  await refresh();
  timer = setInterval(refresh, 1000);
  // 别的页面把我送过来时带的两面旗（两个消费端都在这儿 —— 依赖页不再管这些东西）：
  //  * `autoStartModDownload`：Mod 下载那一步后端**已经在跑**了，接上轮询即可；
  //  * `autoStartDeps`：组件/依赖下载要**由本页发起**（清空重下、完整性补齐、一键更新都走它）。
  if (store.autoStartModDownload) {
    store.autoStartModDownload = false;
    await refresh();
  }
  if (store.autoStartDeps) {
    store.autoStartDeps = false;
    const note = store.autoStartDepsNote || "";
    store.autoStartDepsNote = "";
    await startDeps(note || "开始下载依赖组件…");
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });

// 日志框自动滚到底（不抢鼠标、没新内容不动）
const logBox = ref(null);
useLogAutoScroll(logBox, () => logLines.value);
</script>

<template>
  <div class="space-y-4">
    <!-- 粘网址下载（2026-10-07 从「服装 Mod / 辅助 Mod」页搬过来 —— 用户原话：
         「服装mod、辅助mod下面的 **mod下载卡片挪到下载页**」）。
         卡片本身没动，id 仍是 `mod-download-box`（新手引导第 2 步高亮它）。 -->
    <ModDownloadCard />

    <!-- 汇总：现在到底有没有在下载、多快、队列里几件 -->
    <Card title="下载">
      <template #badge>
        <span class="text-xs" style="color: var(--text-muted)">
          {{ activeCount > 0 ? `${activeCount} 个进行中` : "当前空闲" }}
        </span>
      </template>
      <div class="grid gap-3" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr))">
        <div class="card"><div class="card-body">
          <div class="text-xl font-semibold">{{ activeCount }}</div>
          <div class="text-xs mt-0.5" style="color: var(--text-muted)">进行中的任务</div>
        </div></div>
        <div class="card"><div class="card-body">
          <div class="text-xl font-semibold">{{ speedText(totalSpeed) }}</div>
          <div class="text-xs mt-0.5" style="color: var(--text-muted)">总速度</div>
        </div></div>
        <div class="card"><div class="card-body">
          <div class="text-xl font-semibold">{{ modItems.length }}</div>
          <div class="text-xs mt-0.5" style="color: var(--text-muted)">Mod 队列</div>
        </div></div>
        <div class="card"><div class="card-body">
          <div class="text-xl font-semibold">
            {{ modTask ? counts.imported || 0 : "—" }}
          </div>
          <div class="text-xs mt-0.5" style="color: var(--text-muted)">本次已入库</div>
        </div></div>
      </div>
      <div class="flex flex-wrap items-center gap-2 mt-3">
        <Btn @click="openDir">打开下载目录</Btn>
        <span class="text-xs" style="color: var(--text-muted)">
          下载在后台进行，切到别的页面也不会停；随时可以再往里加任务。
        </span>
      </div>
    </Card>

    <!-- Mod 下载队列 -->
    <Card v-if="hasMods" title="Mod 下载">
      <template #badge>
        <span class="text-xs" style="color: var(--text-muted)">
          {{ counts.imported || 0 }} 入库 · {{ counts.failed || 0 }} 失败
        </span>
      </template>
      <div class="flex flex-wrap gap-2 mb-3">
        <template v-if="modActive">
          <Btn size="sm" @click="control('pause')">暂停</Btn>
          <Btn size="sm" variant="danger" @click="control('cancel')">终止</Btn>
        </template>
        <Btn v-else size="sm" @click="control('resume')">继续</Btn>
        <Btn size="sm" @click="control('clear')">清除记录</Btn>
        <span class="text-xs self-center" style="color: var(--text-muted)">
          「暂停」保留断点，「终止」会清掉半成品。
        </span>
      </div>

      <div class="space-y-2">
        <div v-for="(item, index) in modItems" :key="item.id || index"
             class="flex gap-3 p-2 rounded"
             style="border: 1px solid var(--border); background: var(--surface-2)">
          <!-- 封面（后端转好的 data URI；没有就用占位块） -->
          <div class="w-24 h-14 shrink-0 rounded overflow-hidden flex items-center justify-center"
               style="background: var(--surface); border: 1px solid var(--border)">
            <img v-if="item.cover_data" :src="item.cover_data" class="w-full h-full object-cover" alt="" />
            <span v-else class="text-xs" style="color: var(--text-muted)">无图</span>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm truncate" :title="item.title || item.name">
                {{ item.title || item.name || item.url }}
              </span>
              <Badge :tone="toneOf(item.status)">{{ item.status }}</Badge>
              <span v-if="item.author" class="text-xs" style="color: var(--text-muted)">
                {{ item.author }}
              </span>
            </div>
            <div class="mt-1.5">
              <ProgressBar :value="item.percent || 0"
                           :text="item.size ? `${humanSize(item.received || 0)} / ${humanSize(item.size)}` : ''" />
            </div>
            <div class="text-xs mt-1 flex flex-wrap gap-x-3" style="color: var(--text-muted)">
              <span v-if="item.speed_bps > 0">速度 {{ speedText(item.speed_bps) }}</span>
              <span v-if="item.site_category">{{ item.site_category }}</span>
              <span v-if="item.message" :style="item.status === '失败' ? 'color: var(--danger)' : ''">
                {{ item.message }}
              </span>
            </div>
            <div v-if="item.status === '需手动解压'" class="text-xs mt-1" style="color: var(--warn)">
              已保留原包：{{ item.source_path }} → 手动解压到 {{ item.target_dir }}
            </div>
            <div v-if="item.retired && item.retired.length" class="text-xs mt-1"
                 style="color: var(--text-muted)">
              同来源旧版已移出：{{ item.retired.join("、") }}
            </div>
          </div>
        </div>
      </div>
    </Card>

    <!-- 依赖 / 组件下载（含自更新） -->
    <Card v-if="hasDeps" title="依赖 / 组件">
      <template #badge>
        <span class="text-xs" style="color: var(--text-muted)">
          {{ depTask.running ? speedText(depTask.speed_bps) : (depTask.status || "") }}
        </span>
      </template>
      <div class="text-sm mb-2" style="color: var(--text-muted)">
        {{ depTask.message || "（等待开始…）" }}
      </div>
      <ProgressBar :value="percentOf(depTask)"
                   :text="depTask.total_bytes
                     ? `${humanSize(depTask.done_bytes || 0)} / ${humanSize(depTask.total_bytes)}`
                     : `${Math.round(percentOf(depTask))}%`" />
      <div class="text-xs mt-2" style="color: var(--text-muted)">
        组件更新/补齐没有"暂停"（它是一条顺下来的流程）；要停下就关掉程序再开。
      </div>
      <!-- ⚠️ 日志框**任何情况都是纯黑**（.log-box 在 tokens.css 里）—— 只为与深色主题
           区分边界；`text_select` / user-select 保证可复制（用户明确要过）。 -->
      <div v-if="logLines.length" ref="logBox" class="log-box mt-3"
           style="max-height: 420px; border-radius: 0">{{ logLines.join("\n") }}</div>
    </Card>

    <!-- 空态：说清"这里会出现什么"，而不是一片空白 -->
    <Card v-if="nothing" title="还没有下载任务">
      <p class="text-sm" style="color: var(--text-muted)">
        这里会显示所有下载：在「服装 Mod / 辅助 Mod」页粘贴网址、或在「Mod 商城」里点下载，
        任务都会出现在这儿；点「一键启动」时补齐依赖组件的下载也在这儿。
      </p>
      <p class="text-xs mt-2" style="color: var(--text-muted)">
        下载全程在后台跑，切页不会中断，也可以随时继续追加新任务。
      </p>
    </Card>
  </div>
</template>
