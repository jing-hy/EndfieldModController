<script setup>
// 全局弹窗宿主：渲染 uiState.dialog，语义与旧 app.js 的 showModalDialog 完全一致
// （正文用 textContent 等价方式渲染 → 这里直接用插值，**不解析 markdown**）。
import { ref, watch, nextTick, onUnmounted } from "vue";
import { computed } from "vue";
import { call } from "../lib/bridge.js";
import { uiState, resolveDialog } from "../lib/dialog.js";
// ⚠️ `escapeHtml` 复用 `lib/util.js` 的唯一实现（2026-10-04）：本文件原先自己又抄了一份
// （逐字节相同），改一处漏一处 —— 而这个函数是**弹窗正文的 XSS 防线**，更不能有两份。
import { escapeHtml } from "../lib/util.js";
import Btn from "./ui/Btn.vue";

// 破坏性动作默认把焦点放在**安全项**（取消）上 —— `focusCancel: true` 时。
// 用户定的交互准则：「破坏性动作写清后果、默认聚焦安全项」。
const cancelBtn = ref(null);
const okBtn = ref(null);

// ⚠️ **强制停留倒计时**（2026-10-03 加）。用户 2026-09-30 要求：异常状态预警必须
// "强制用户停留一定秒数（可在仓库配置，默认 10s）" —— 倒计时结束前所有按钮不可点。
// 这是"必须让人看见"类提示的硬要求，不是装饰。
const holdLeft = ref(0);
let holdTimer = null;

// ── 输入型弹窗（2026-10-05 加）──────────────────────────────────────────────
// `input`：弹窗里带一个输入框，确认时把**输入的文本**交回去（重命名用）；
// `requireText`：必须逐字输入指定内容，确认按钮才会亮（彻底删除要用户手输 ok）。
const inputValue = ref("");
const inputRef = ref(null);
const needText = computed(() => String(uiState.dialog?.requireText || ""));
const hasInput = computed(() => !!(uiState.dialog?.input || needText.value));
const textMatched = computed(() => {
  if (!needText.value) return true;
  return inputValue.value.trim().toLowerCase() === needText.value.trim().toLowerCase();
});
const canOk = computed(() => holdLeft.value <= 0 && textMatched.value);

function confirmDialog() {
  const dialog = uiState.dialog;
  if (!dialog || !canOk.value) return;
  resolveDialog(dialog.input ? inputValue.value.trim() : true);
}

function stopHold() {
  if (holdTimer) { clearInterval(holdTimer); holdTimer = null; }
  holdLeft.value = 0;
}

watch(() => uiState.dialog, async (dialog) => {
  stopHold();
  inputValue.value = dialog && dialog.input ? String(dialog.input.value || "") : "";
  if (!dialog) return;
  await nextTick();
  // 有输入框时**焦点先给输入框**：不管是重命名还是"输入 ok 确认"，焦点落在按钮上
  // 都等于逼用户先用鼠标点一下输入框，多此一举。
  const target = dialog.input ? inputRef.value : (dialog.focusCancel ? cancelBtn.value : okBtn.value);
  if (target && target.focus) target.focus();
  const hold = Number(dialog.holdSeconds || 0);
  if (hold > 0) {
    holdLeft.value = hold;
    holdTimer = setInterval(() => {
      holdLeft.value -= 1;
      if (holdLeft.value <= 0) stopHold();
    }, 1000);
  }
}, { immediate: true });

onUnmounted(stopHold);

// ⚠️⚠️ **弹窗正文的轻量渲染**（2026-10-03 用户：「**你这里并不会渲染成加粗**」）。
//
// 原来这里是 `{{ uiState.dialog.message }}` —— **纯文本插值**，`dialog.js` 的注释里也
// 明确写着"不允许写 markdown"。所以我写的 `**压缩包**` 会**原样显示成星号**，
// 界面很难看。现在做一层**受控**渲染：
//   * 先**整体 HTML 转义**（正文可能含用户文件名，绝不能直接 v-html 注入）；
//   * 再把 `**…**` 换成 `<b>`；
//   * 再把**路径**（`X:\…` 或 `/…`）自动变成可点击的 `<a>`，点一下调
//     `open_path_in_explorer` 打开它的所在位置 —— 用户不用再手动复制路径。
// 只此三种变换，其余一律按纯文本走。

// 形如 `D:\a\b`（含空格的路径用引号包着的情况也认）
const PATH_RE = /([A-Za-z]:\\[^\n<>"']+?|(?:\\\\)[^\n<>"']+?)(?=[\s，。；、）)\]"]|$)/g;

const renderedMessage = computed(() => {
  const raw = String(uiState.dialog?.message ?? "");
  let html = escapeHtml(raw);
  // `**加粗**`（转义后 ** 不受影响）
  html = html.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  // 路径 → 可点击。跳过已经被包进 <b> 里的情况（正则只认盘符/UNC 开头，够用）
  html = html.replace(PATH_RE, (match) => {
    const clean = match.replace(/[.,;:，。；：]+$/, "");
    const tail = match.slice(clean.length);
    return `<a class="dlg-path" data-path="${clean}" title="点击打开所在位置">${clean}</a>${tail}`;
  });
  return html;
});

/** 弹窗里出现的第一个路径（有的话就给一个「打开文件夹」按钮）。 */
const firstPath = computed(() => {
  const raw = String(uiState.dialog?.message ?? "");
  const m = raw.match(/[A-Za-z]:\\[^\n<>"']+/);
  return m ? m[0].replace(/[.,;:，。；：)\]]+$/, "") : "";
});

/** 点路径 / 点按钮 → 让后端在资源管理器里定位它（后端有白名单，安全）。 */
async function openPath(path) {
  const target = String(path || "").trim();
  if (!target) return;
  try {
    const r = await call("open_path_in_explorer", target);
    const { showToast } = await import("../lib/dialog.js");
    if (r && r.ok === false) showToast(String(r.message || "打不开这个位置"), "danger");
  } catch (e) {
    /* 打不开就算了，用户还能手动复制 */
  }
}

// 事件委托：`v-html` 出来的链接没法直接绑 @click
function onMessageClick(event) {
  const el = event.target && event.target.closest && event.target.closest("a[data-path]");
  if (!el) return;
  event.preventDefault();
  openPath(el.getAttribute("data-path"));
}
</script>
<template>
  <div v-if="uiState.dialog" class="fixed inset-0 z-50 flex items-center justify-center"
       style="background: rgba(0,0,0,.45)">
    <!-- ⚠️ `min-w-0` + `overflow-hidden` 是关键：卡片是 flex 子项，而 flex 子项默认
         `min-width: auto` —— 里面的超长路径会把整张卡片**顶宽**，光给 <pre> 加折行还不够。 -->
    <div class="card w-[min(560px,92vw)] min-w-0 overflow-hidden shadow-lg" style="background: var(--surface)">
      <div class="card-head">{{ uiState.dialog.title }}</div>
      <div class="card-body min-w-0">
        <!-- ⚠️ 长路径必须在**斜杠处自然折行**（用户 2026-10-03：「不是限高的问题，应该是限宽的问题，
             好像一个路径必须要一行显示完，实际可以在 / 处换行」）。
             `break-words`（overflow-wrap: break-word）**不够** —— 它只在"整个单词放不下"时才断，
             而 Windows 路径没有空格、会被当成**一个超长单词**，于是一行撑出弹窗外。
             `overflow-wrap: anywhere` 允许在任意字符处断行（含 `/`），再配 `max-width: 100%`
             把宽度约束在弹窗内；限高 + 滚动是额外保险（超长堆栈仍然要能看全）。 -->
        <!-- ⚠️ 用 `v-html` 渲染**受控**轻量标记（`**加粗**` + 可点路径）——
             内容已先在 `renderedMessage` 里整体 HTML 转义，只放行我们自己的 <b>/<a>。 -->
        <pre class="whitespace-pre-wrap m-0 text-sm leading-6 dlg-body"
             style="max-width: 100%; overflow-wrap: anywhere; word-break: break-word;
                    max-height: 46vh; overflow-y: auto"
             v-html="renderedMessage" @click="onMessageClick"></pre>
        <!-- 输入区（重命名的新名字 / 彻底删除的"输入 ok"）——
             `requireText` 没输对时确认按钮是灰的，并在下面说清还差什么。 -->
        <div v-if="hasInput" class="mt-3">
          <div v-if="uiState.dialog.input && uiState.dialog.input.label"
               class="text-xs mb-1" style="color: var(--text-muted)">
            {{ uiState.dialog.input.label }}
          </div>
          <input ref="inputRef" class="field" type="text" autocomplete="off" spellcheck="false"
                 :value="inputValue"
                 :placeholder="uiState.dialog.input ? uiState.dialog.input.placeholder : ''"
                 :maxlength="uiState.dialog.input && uiState.dialog.input.maxlength
                            ? uiState.dialog.input.maxlength : null"
                 @input="inputValue = $event.target.value"
                 @keyup.enter="confirmDialog" />
          <div v-if="!textMatched" class="text-xs mt-1" style="color: var(--text-muted)">
            把 {{ needText }} 照原样输进去，确认按钮才会亮。
          </div>
        </div>
        <a v-if="uiState.dialog.link && uiState.dialog.link.url" :href="uiState.dialog.link.url"
           class="text-accent text-xs mt-2 inline-block" @click.prevent="$emit('open-link', uiState.dialog.link.url)">
          {{ uiState.dialog.link.text || uiState.dialog.link.url }}
        </a>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t items-center" style="border-color: var(--border)">
        <!-- 强制停留：倒计时没走完时所有按钮都不可点（用户要求"强制用户停留一定秒数"） -->
        <span v-if="holdLeft > 0" class="text-xs mr-auto" style="color: var(--text-muted)">
          请先读完（{{ holdLeft }} 秒后可操作）
        </span>
        <!-- ⚠️ **路径旁边要有「打开」入口**（2026-10-03 用户：「**还有没有打开按钮**」）。
             出现路径时才显示；点它等同于点路径本身（后端有白名单，安全）。 -->
        <Btn v-if="firstPath" variant="secondary" :disabled="holdLeft > 0"
             class="mr-auto" @click="openPath(firstPath)">打开文件夹</Btn>
        <Btn v-if="uiState.dialog.showCancel" ref="cancelBtn" variant="secondary"
             :disabled="holdLeft > 0" @click="resolveDialog(false)">
          {{ uiState.dialog.cancelText }}
        </Btn>
        <Btn v-for="b in uiState.dialog.extraButtons" :key="b.text" variant="secondary"
             :disabled="holdLeft > 0"
             @click="resolveDialog(b.value === undefined ? true : b.value)">{{ b.text }}</Btn>
        <Btn ref="okBtn" variant="primary" :disabled="!canOk"
             @click="confirmDialog">{{ uiState.dialog.okText }}</Btn>
      </div>
    </div>
  </div>
</template>
