// 日志框的"智能自动滚动"。
//
// 用户 2026-10-03 的两条要求：
//   ① 「日志也不会自动滚到最下面」—— 有新内容时要自动跟到底；
//   ② 「自动滚到最下面不要和用户抢鼠标，只要没有新的内容就不动」——
//      用户翻上去看历史时**绝不能**把他拽回底部；内容没变时也一次都不动。
//
// 关键：**"用户是不是贴着底部"必须在内容变化之前就知道**。
// 如果在 watch 回调里现算，那时 DOM 已经变长、scrollTop 没跟上的话必然算成"不在底部"，
// 于是永远不会自动滚。所以这里用 scroll 事件持续记录用户意图（sticky），
// 只有 sticky === true 才跟到底 —— 用户一旦往上滚，sticky 立刻变 false，从此不打扰他。
import { onUnmounted, watch } from "vue";

const BOTTOM_TOLERANCE = 24;   // 距底部 24px 内都算"贴着底部"（少量取整误差）

export function useLogAutoScroll(elRef, textRef) {
  let sticky = true;           // 是否跟随到底（用户往上滚后变 false）
  let observer = null;
  let attached = null;

  function atBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_TOLERANCE;
  }

  function attach(el) {
    if (attached === el) return;
    attached = el;
    if (observer) observer.disconnect();
    if (!el) return;
    const onScroll = () => { sticky = atBottom(el); };
    el.addEventListener("scroll", onScroll, { passive: true });
    // 元素可能被 v-if 换掉，卸载时一并清理
    observer = new MutationObserver(() => {
      if (!document.body.contains(el)) {
        el.removeEventListener("scroll", onScroll);
        sticky = true;
        attached = null;
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  watch([elRef, textRef], () => {
    const el = elRef.value;
    if (!el) { attached = null; return; }
    attach(el);
    // 只有"用户本来就在底部"才跟到底；否则一动不动（不抢鼠标）
    if (!sticky) return;
    // 内容在一次 DOM 更新后才会变长，等一帧再滚
    requestAnimationFrame(() => {
      if (sticky && elRef.value === el) el.scrollTop = el.scrollHeight;
    });
  }, { flush: "post" });

  onUnmounted(() => {
    if (observer) observer.disconnect();
    if (attached) attached = null;
  });
}
