// 「⋯ 更多」这类**就地浮层**的定位（服装页 / 辅助页共用这一份）。
//
// ⚠️ 2026-10-05 用户原话：「**不要定死更多的浮窗位置，现在靠下的时候会出去**」。
// 病根是两个页面各自写死一个"估计高度"（服装页 190、辅助页 200）再拿 `innerHeight` 去减：
// 菜单项一多（这一版刚加了重命名 / 更换预览图 / 彻底删除）估计值立刻偏小，
// 卡片靠在窗口下沿时菜单底部就跑到窗口外面、最后几项点不到。
//
// 现在的口径：
//   ① 尺寸**实测**（渲染出来后读 `offsetWidth` / `offsetHeight`），不猜；
//   ② 下方放不下就**翻到按钮上方**，四周再统一夹进视口（至少留 8px）；
//   ③ 逻辑只有这一份 —— 别再在页面里各抄一遍"夹取"。
export const MENU_GAP = 4;
export const MENU_MARGIN = 8;

/**
 * 纯函数：给按钮矩形 + 菜单尺寸 + 视口尺寸，返回夹取后的 `{ x, y }`。
 *
 * @param {{left:number,top:number,right:number,bottom:number}} box 触发按钮的矩形
 * @param {{width?:number,height?:number}} size 菜单实测尺寸（拿不到高度时传 0，只做横向夹取）
 * @param {{width?:number,height?:number}} viewport 视口尺寸（`window.innerWidth/innerHeight`）
 */
export function placeMenu(box, size, viewport) {
  const vw = Number((viewport || {}).width) || 1200;
  const vh = Number((viewport || {}).height) || 800;
  const w = Number((size || {}).width) || 176;
  const h = Math.max(0, Number((size || {}).height) || 0);
  // 竖直方向允许落到的最大值：再往下就出界了（h=0 时退化成"贴着底边"）
  const limitY = Math.max(MENU_MARGIN, vh - h - MENU_MARGIN);

  // 横向：默认右对齐到那个「⋯」，再夹进视口
  let x = box.right - w;
  x = Math.min(x, vw - w - MENU_MARGIN);
  x = Math.max(MENU_MARGIN, x);

  // 纵向：默认往下弹；下方不够就翻到按钮上方；都放不下才退回"贴着下沿"（配 max-height 滚动）
  let y = box.bottom + MENU_GAP;
  if (h && y > limitY) {
    const above = box.top - h - MENU_GAP;
    y = above >= MENU_MARGIN ? above : limitY;
  }
  y = Math.max(MENU_MARGIN, Math.min(y, limitY));

  return { x: Math.round(x), y: Math.round(y) };
}
