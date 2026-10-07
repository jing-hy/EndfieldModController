<script setup>
// 「下载 Mod」卡片 —— **现在只在「下载」页**。
//
// 2026-10-07 搬迁：原先它同时出现在「服装 Mod」与「辅助 Mod」页（2026-10-03 用户要求
// 「还有辅助mod下面也要留一样的下载mod卡片」），这轮用户要求「服装mod、辅助mod下面的
// **mod下载卡片挪到下载页**」⇒ 两个页面里的都删掉，只留在这里（发起下载与看进度同页）。
//
// 设计要点（用户明确要求，照旧）：
//   * 卡片里**只有输入框与「开始下载」**；
//   * **卡片本身不要有任何变化**（不要下载条、不要进度文案）——「mod下载卡片不要有其他变化，
//     如下载条这些」。进度与日志在同页下方的任务列表里看。
//   * 卡片 id 仍是 `mod-download-box`：新手引导第 2 步靠它高亮（`App.vue` 的引导步骤已同步
//     改成 `tab: "downloads"`，否则会去高亮一个本页不存在的元素）。
import { ref } from "vue";
import { call } from "../lib/bridge.js";
import { store } from "../store.js";
import { showAlert, showToast } from "../lib/dialog.js";
import Card from "./ui/Card.vue";
import Btn from "./ui/Btn.vue";

const text = ref("");
const busy = ref(false);

async function startDownload() {
  const value = String(text.value || "").trim();
  if (!value) { await showAlert("还没填网址", "把 Mod 的下载网址粘进来，一行一个。"); return; }
  busy.value = true;
  try {
    const r = await call("start_mod_download", value);
    if (!r || r.ok === false) {
      await showAlert("没能开始下载", (r && r.message) || "未知原因");
      return;
    }
    text.value = "";
    showToast(`已加入下载队列（共 ${r.queued || r.total} 个）—— 下方列表能看到进度`, "success");
    // 任务已经进队列了；这里只是把 store 里的活跃数刷新一下（徽标与汇总卡都读它）
    store.autoStartModDownload = true;
    store.activeDownloads = Math.max(store.activeDownloads, 1);
  } catch (e) { /* call 已弹窗 */ } finally {
    busy.value = false;
  }
}

async function openDir() {
  // ⚠️ 下载目录有**专用接口** `open_download_dir`（0.9.5 用的就是它）——
    // 传 "downloads" 这个标签给 `open_path_in_explorer` 会被当成路径、必然失败（2026-10-03 修）。
    const r = await call("open_download_dir");
    if (r && r.ok === false) showToast(String(r.message || "打不开下载目录"), "danger");
}
</script>

<template>
  <!-- ⚠️ **C6：这个 id 是新手引导第 2 步的高亮目标**（2026-10-03 补回归）。
       0.9.5 的引导第 2 步指向 `#mod-download-box`，换代后那个 id **不存在**
       ⇒ 第二步没有聚光高亮、只能把卡片居中显示，用户看不出该点哪。 -->
  <Card title="下载 Mod" id="mod-download-box">
    <template #badge><span class="text-xs" style="color: var(--text-muted)">粘网址，一行一个</span></template>
    <p class="text-xs mb-2" style="color: var(--text-muted)">
      支持直链，也支持<b>香蕉网（GameBanana）页面地址</b> —— 会自动换成真实文件直链，并带出封面。
      zip / 7z / rar 下完自动解压进库并识别角色；<b>正在下载时还能继续往里加</b>（不必等上一批跑完）。
      进度、速度与日志就在下面这一页。
    </p>
    <textarea v-model="text" class="field font-mono text-xs" rows="3"
              placeholder="https://gamebanana.com/mods/721442&#10;https://example.com/another-mod.7z"></textarea>
    <div class="flex items-center gap-2 mt-2">
      <Btn variant="primary" :disabled="busy" @click="startDownload">开始下载</Btn>
      <Btn @click="openDir">打开下载目录</Btn>
    </div>
  </Card>
</template>
