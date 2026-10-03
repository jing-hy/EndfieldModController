<script setup>
// 「下载 Mod」卡片 —— **Mod 库页与辅助 Mod 页共用**（用户 2026-10-03：
// 「还有辅助mod下面也要留一样的下载mod卡片」）。
//
// 设计要点（用户明确要求）：
//   * 卡片里**只有输入框与「开始下载」**，点了就**跳到「依赖」页**去下载 ——
//     「mod下载应该跳转到依赖页下载，过程中显示日志那些」；
//   * **卡片本身不要有任何变化**（不要下载条、不要进度文案）——「mod下载卡片不要有其他变化，
//     如下载条这些」。进度与日志统一在依赖页看，那儿的日志框本来就是给下载用的。
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
    showToast(`已开始 ${r.total} 个下载任务，正在跳到「依赖」页`, "success");
    // 跳到依赖页：那儿的日志框会显示每一条的进度与结果，失败了也看得到原因
    store.autoStartModDownload = true;
    store.tab = "dependencies";
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
  <Card title="下载 Mod">
    <template #badge><span class="text-xs" style="color: var(--text-muted)">粘网址，一行一个</span></template>
    <p class="text-xs mb-2" style="color: var(--text-muted)">
      支持直链，也支持<b>香蕉网（GameBanana）页面地址</b> —— 会自动换成真实文件直链，并带出封面。
      zip / 7z / rar 下完自动解压进库并识别角色。开始后会自动跳到「依赖」页，那里能看到下载日志。
    </p>
    <textarea v-model="text" class="field font-mono text-xs" rows="3"
              placeholder="https://gamebanana.com/mods/721442&#10;https://example.com/another-mod.7z"></textarea>
    <div class="flex items-center gap-2 mt-2">
      <Btn variant="primary" :disabled="busy" @click="startDownload">开始下载</Btn>
      <Btn @click="openDir">打开下载目录</Btn>
    </div>
  </Card>
</template>
