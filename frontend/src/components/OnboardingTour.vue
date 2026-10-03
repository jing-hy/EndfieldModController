<script setup>
// 新手引导（分步 tour）：挖孔聚光高亮目标控件 + **箭头指向它** + 气泡说明。
//
// 移植自 0.4.0 的 `web/app.js` + `web/style.css`（那版用户是满意的），
// 差别只有两处：① 换成 Vue 组件；② **加了指向目标的箭头**（用户 2026-10-03：
// 「我需要那种一个箭头指向按钮的那种」——旧版只有挖孔高亮，没有箭头）。
//
// 定位逻辑沿用旧版的做法：切页 → **等两帧**（切页后布局才稳定）→ 量目标矩形 →
// 聚光对齐（外扩 8px）→ 卡片贴目标下方，放不下就挪到上方；没有目标时卡片居中。
import { ref, watch, nextTick } from "vue";
import { store } from "../store.js";
import Btn from "./ui/Btn.vue";

const props = defineProps({
  steps: { type: Array, required: true },
  modelValue: { type: Boolean, default: false },
});
const emit = defineEmits(["update:modelValue", "finish"]);

const index = ref(0);
const spot = ref({ left: "50%", top: "40%", width: "0px", height: "0px" });
const card = ref({ left: "50%", top: "46%", transform: "translate(-50%, 0)" });
// 箭头：朝上（卡片在目标下方）或朝下（卡片在目标上方）；无目标时隐藏
const arrow = ref({ show: false, left: "0px", top: "0px", dir: "up" });

const PAD = 8;          // 聚光比目标外扩多少
const CARD_W = 420;     // 与 CSS 的 max-width 一致
const GAP = 16;         // 卡片与目标的间距（箭头就画在这个缝里）

function current() { return props.steps[index.value] || null; }

async function layout() {
  const step = current();
  if (!step) return;
  if (step.tab && store.tab !== step.tab) store.tab = step.tab;
  await nextTick();

  // ⚠️ 切页之后目标元素**不一定已经渲染出来**（页面组件要挂载一次）。
  // 旧版 `tourShow` 用的是全局 DOM + 手写 id，切页是同步的，所以量得到；
  // Vue 这边切页是异步的 —— 一开始没重试，result 就是 `getElementById` 返回 null、
  // 走了"无目标 → 卡片居中"的分支（聚光框宽高 0、看不见，但卡片照常显示）。
  // 这里最多等 ~500ms 才放弃。
  let el = null;
  for (let attempt = 0; attempt < 25 && !el; attempt += 1) {
    el = step.target ? document.getElementById(step.target) : null;
    if (el) break;
    // 用 setTimeout 而不是 requestAnimationFrame：隐藏窗口/无 GPU 的环境（以及后台标签页）
    // 里 rAF 可能长时间不推进，循环就卡死、后面的定位代码永不执行 —— 卡片会停在初始的
    // "居中"位置（我就是在 headless 截图里踩到这个的）。
    await new Promise((r) => setTimeout(r, 16));
  }

  if (el && el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "instant" });
  // 再等两帧：滚动/布局稳定后 rect 才准（旧版同样是"等两帧再量"）
  await new Promise((r) => setTimeout(r, 32));

  if (!el) {
    // 真的没有具体目标（或元素始终没出现）：聚光收成一个点，卡片居中，不画箭头
    spot.value = { left: "50%", top: "40%", width: "0px", height: "0px" };
    card.value = { left: "50%", top: "46%", transform: "translate(-50%, 0)" };
    arrow.value = { show: false, left: "0px", top: "0px", dir: "up" };
    return;
  }
  const r = el.getBoundingClientRect();
  spot.value = {
    left: `${r.left - PAD}px`, top: `${r.top - PAD}px`,
    width: `${r.width + PAD * 2}px`, height: `${r.height + PAD * 2}px`,
  };
  const below = r.bottom + GAP;
  const fitsBelow = below + 240 < window.innerHeight;
  const cardTop = fitsBelow ? below : Math.max(16, r.top - GAP - 220);
  const cardLeft = Math.min(Math.max(16, r.left), Math.max(16, window.innerWidth - CARD_W - 16));
  card.value = { left: `${cardLeft}px`, top: `${cardTop}px`, transform: "none" };
  // 箭头：卡在卡片与目标之间的缝里，水平指向目标中心
  const targetCx = r.left + r.width / 2;
  const arrowLeft = Math.min(Math.max(12, targetCx - cardLeft - 8), CARD_W - 28);
  arrow.value = {
    show: true,
    left: `${arrowLeft}px`,
    top: fitsBelow ? `${cardTop - 9}px` : `${cardTop + 214}px`,
    dir: fitsBelow ? "up" : "down",
  };
}

function go(delta) {
  const next = index.value + delta;
  if (next < 0) return;
  if (next >= props.steps.length) { finish(); return; }
  index.value = next;
  layout();
}

function finish() {
  emit("update:modelValue", false);
  emit("finish");
}

watch(() => props.modelValue, (visible) => {
  if (visible) { index.value = 0; layout(); }
}, { immediate: true });
</script>

<template>
  <div v-if="modelValue" class="tour-root">
    <!-- 聚光：超大 box-shadow 把四周压暗（旧版同款做法），只留目标区域透亮 -->
    <div class="tour-spot" :style="spot"></div>

    <!-- 指向目标的箭头（三角形，跟着卡片上下翻转） -->
    <div v-if="arrow.show" class="tour-arrow" :class="`tour-arrow-${arrow.dir}`"
         :style="{ left: arrow.left, top: arrow.top }"></div>

    <div class="tour-card" :style="card">
      <div class="tour-progress">{{ index + 1 }} / {{ steps.length }}</div>
      <h3 class="tour-title">{{ current() ? current().title : "" }}</h3>
      <div class="tour-body">{{ current() ? current().body : "" }}</div>
      <div class="tour-actions">
        <button class="btn" @click="finish">跳过引导</button>
        <button class="btn" :style="{ visibility: index === 0 ? 'hidden' : 'visible' }"
                @click="go(-1)">上一步</button>
        <Btn variant="primary" @click="go(1)">
          {{ index === steps.length - 1 ? "开始使用" : "下一步" }}
        </Btn>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tour-root { position: fixed; inset: 0; z-index: 800; }
.tour-spot {
  position: fixed;
  border-radius: 10px;
  /* 挖孔遮罩：一圈超大的实心阴影把除目标外的区域压暗，再给目标描一圈主色边 */
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, .55), 0 0 0 2px var(--accent) inset;
  transition: left .22s ease, top .22s ease, width .22s ease, height .22s ease;
  pointer-events: none;
}
.tour-arrow {
  position: fixed;
  width: 0; height: 0;
  border-left: 9px solid transparent;
  border-right: 9px solid transparent;
  transition: left .22s ease, top .22s ease;
  pointer-events: none;
  z-index: 801;
}
.tour-arrow-up { border-bottom: 9px solid var(--accent); }
.tour-arrow-down { border-top: 9px solid var(--accent); }
.tour-card {
  position: fixed;
  width: 420px;
  max-width: calc(100vw - 32px);
  padding: 16px 18px;
  border-radius: var(--radius);
  background: var(--surface);
  border: 1px solid var(--border);
  box-shadow: 0 18px 50px rgba(0, 0, 0, .35);
  transition: left .22s ease, top .22s ease;
  z-index: 802;
}
.tour-progress { font-size: 12px; color: var(--text-muted); }
.tour-title { margin: 6px 0 8px; font-size: 15px; font-weight: 600; }
.tour-body { font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
.tour-actions { margin-top: 14px; display: flex; justify-content: flex-end; gap: 8px; }
</style>
