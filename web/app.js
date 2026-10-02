const state = { config: {}, mods: [], dependency_report: {}, selected: new Set(), lastPrepare: null, fileWatchdog: null, modfixTool: null };

// 反馈途径（用户 2026-10-01 要求：所有反馈相关弹窗/说明/README 都要带上 QQ 群）
const FEEDBACK_QQ = '1045239747';
const FEEDBACK_QQ_ANSWER = 'jing_hy';

// 后端返回的字符串（Mod 名、角色名、分组、文件路径、错误信息）一律先转义再拼进 HTML。
// 这些内容来自用户导入的 mod 包与下载的依赖清单 —— 直接拼模板等于把"包名"当代码执行，
// 而 WebView 里能拿到 window.pywebview.api.*（open_path / apply_app_update 等）。
function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// 与 index.html 的 <head> 内联脚本保持**同一份白名单**：两边不一致时，
// 首屏先按缓存上色、随后 app.js 又把它规范化成 dark —— 页面当场变深，
// 而且用户的选择会被永久改写进 localStorage（2026-10-01 修）。
const THEMES = ['light', 'dark', 'amber', 'cyan', 'violet', 'emerald'];

function applyTheme(theme) {
  const value = THEMES.includes(theme) ? theme : 'light';
  document.documentElement.dataset.theme = value;
  try { localStorage.setItem('mc-theme', value); } catch (err) { /* ignore */ }
  const button = document.getElementById('theme-toggle');
  if (button) button.textContent = value === 'light' ? '浅色' : '深色';
  const select = document.getElementById('cfg-theme');
  if (select) select.value = value;
}

try { applyTheme(localStorage.getItem('mc-theme') || 'light'); } catch (err) { /* ignore */ }

// 前端错误上报：任何未捕获异常/未处理 rejection 都写进后端日志，
// 这样"界面空白 / 点不动"这类问题也能在 runtime\logs 里看到原因。
(function () {
  function report(kind, msg) {
    try {
      if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.log_frontend_error(`${kind}: ${msg}`);
      }
    } catch (err) { /* ignore */ }
  }
  window.addEventListener('error', function (e) {
    report('error', `${e.message} @ ${e.filename || '?'}:${e.lineno || 0}:${e.colno || 0}`);
  });
  window.addEventListener('unhandledrejection', function (e) {
    const r = e.reason;
    report('rejection', String((r && (r.message || r.stack)) || r));
  });
})();

function $(id) { return document.getElementById(id); }
// 顶部气泡：右上角那行灰字已按用户要求去掉（CSS 里 #global-status 隐藏），
// 状态改为顶部居中的圆角气泡，几秒后自动向上收起。
let toastTimer = null;
let lastToastText = '';

function showToast(text, ms = 3400) {
  const el = $('toast');
  if (!el || !text) return;
  // 同一条消息连续出现时不重复弹（setStatus 在轮询里会被高频调用）
  if (text === lastToastText && el.classList.contains('show')) return;
  lastToastText = text;
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

function setStatus(text) {
  const el = $('global-status');
  if (el) el.textContent = text;   // 元素已隐藏，保留写入只为兼容调试
  if (text) showToast(text);
}

// ── 统一弹窗 ────────────────────────────────────────────────────────────────
// 与「检测到终末地异常退出」那个模态（#crash-modal）**完全同一套结构与样式**：
// .modal / .modal-content / .modal-header / .modal-actions。
// 用户要求把所有弹窗都改成它那个样式，因此这里提供 Promise 版的 showAlert /
// showConfirm 取代原生 alert/confirm（原生弹窗由系统渲染、改不了样式），
// 全项目 27 处调用已批量替换过来。
function showModalDialog({ title, message, okText = '确定', cancelText = '取消', showCancel = true, link = null, extraButtons = [] }) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal';
    wrap.innerHTML = '<div class="modal-content" style="width:min(560px,92vw)">'
      + '<div class="modal-header"><h3></h3></div>'
      + '<pre class="modal-body"></pre>'
      + '<div class="modal-actions"></div></div>';
    wrap.querySelector('h3').textContent = title;
    wrap.querySelector('.modal-body').textContent = message;
    if (link && link.url) {
      // 正文里的网址**直接点开**，不再配一个「打开」按钮（用户 2026-10-01 要求）；
      // 点击由 boot 里注册的全局委托转给 open_external。
      const anchor = document.createElement('a');
      anchor.className = 'ext-link';
      anchor.href = link.url;
      anchor.target = '_blank';
      anchor.rel = 'noopener';
      anchor.textContent = link.text || link.url;
      wrap.querySelector('.modal-body').after(anchor);
    }
    const actions = wrap.querySelector('.modal-actions');
    let settled = false;
    const onKey = (event) => {
      // 只让**栈顶**弹窗响应键盘：多个弹窗同时存在时（例如轮询失败叠加），
      // 一次 Enter 会把所有确认框一起按掉，其中包括"净化游戏目录"这类危险操作
      // （2026-10-01 修）。
      const modals = document.querySelectorAll('.modal');
      if (modals.length && modals[modals.length - 1] !== wrap) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        finish(false);
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        finish(true);
      }
    };
    const finish = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKey);
      wrap.remove();
      resolve(value);
    };
    if (showCancel) {
      const cancel = document.createElement('button');
      cancel.textContent = cancelText;
      cancel.onclick = () => finish(false);
      actions.appendChild(cancel);
    }
    // 可选中间按钮（用户 2026-10-01 的冲突处理需要一个三选一弹窗）：
    // 顺序按他的准则排 —— 冒险项在最左（cancelText）、推荐/主选在最右（primary）。
    for (const extra of (Array.isArray(extraButtons) ? extraButtons : [])) {
      if (!extra || !extra.text) continue;
      const button = document.createElement('button');
      button.textContent = String(extra.text);
      button.dataset.extraValue = String(extra.value ?? extra.text);
      button.onclick = () => finish(String(extra.value ?? extra.text));
      actions.appendChild(button);
    }
    const ok = document.createElement('button');
    ok.className = 'primary';
    ok.textContent = okText;
    ok.onclick = () => finish(true);
    actions.appendChild(ok);
    document.addEventListener('keydown', onKey);
    document.body.appendChild(wrap);
    ok.focus();
  });
}

// ── 「选择要保留的 Mod」弹窗（用户 2026-10-01 要求）────────────────────────
// 场景：**确定是皮肤（Mod）冲突**时给一个选项「一键关闭其中一个（自行选择）」→
// 点了之后**先关掉原弹窗**，再弹这一个：
//   · **每组冲突一个下拉框**，选你要保留的那个（同组其余会被取消勾选）；
//   · 只改**勾选**，绝不动 Mod 库（不删除、不移动文件）；
//   · 确认后自动跑一次「生成控制器」，让 staging 立刻变干净。
// ⚠ 入口**只在崩溃归因弹窗**（终末地因为皮肤冲突崩了）里 —— 用户 2026-10-01 明确：
//   「我说的自选保留一个 mod 应该在终末地崩溃而且是皮肤冲突导致的那里，**启动时那个
//     只做提示**，不需要只保留一个这个按钮」。
// 返回值：后端结果对象（成功）或 false（取消）。
async function showConflictResolveModal() {
  let groups = [];
  try {
    const info = await call('conflict_groups');
    groups = (info && info.groups) || [];
  } catch (err) {
    await showAlert(`读取冲突信息失败：${err}`, '读取失败');
    return false;
  }
  if (!groups.length) {
    await showAlert('当前没有可以自动处理的冲突（可能已经清理过，或者是手动放进 Mods 的目录）。',
      '没有可处理的冲突');
    return false;
  }
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal';
    const content = document.createElement('div');
    content.className = 'modal-content';
    content.style.width = 'min(640px, 94vw)';

    const header = document.createElement('div');
    header.className = 'modal-header';
    const heading = document.createElement('h3');
    heading.textContent = '选择要保留的 Mod';
    header.appendChild(heading);
    content.appendChild(header);

    const tip = document.createElement('p');
    tip.className = 'hint';
    tip.textContent = '下面每组里的 Mod 覆盖同一批游戏资源，同时启用会互相覆盖'
      + '（表现成某个 Mod「不加载」，或在加载时闪退）。每组请选一个保留，'
      + '其余的会自动取消勾选 —— 只改勾选，不会删除或移动你的 Mod 文件。';
    content.appendChild(tip);

    const picked = new Map();          // 组序号 -> 该组要保留的 mod id
    groups.forEach((group, index) => {
      const entries = (group.mods || []).filter((entry) => entry);
      const block = document.createElement('div');
      block.className = 'conflict-group';
      const label = document.createElement('div');
      label.className = 'conflict-group-title';
      label.textContent = `冲突组 ${index + 1}（共享 ${(group.shared || []).length} 个资源标识）`;
      block.appendChild(label);

      const select = document.createElement('select');
      select.dataset.conflictGroup = String(index);
      const usable = entries.filter((entry) => entry.id);
      entries.forEach((entry, entryIndex) => {
        const option = document.createElement('option');
        option.value = String(entry.id || '');
        option.textContent = String(entry.name || entry.id || `Mod ${entryIndex + 1}`);
        option.selected = entryIndex === 0;
        select.appendChild(option);
      });
      picked.set(index, String((usable[0] || {}).id || ''));
      select.onchange = () => picked.set(index, select.value);
      if (!usable.length) {
        select.disabled = true;
        const warn = document.createElement('div');
        warn.className = 'hint';
        warn.textContent = '这一组在 Mod 库里定位不到（可能是手动放进 Mods 的目录）—— 需要手动处理。';
        block.appendChild(warn);
      }
      block.appendChild(select);
      if ((group.shared || []).length) {
        const detail = document.createElement('div');
        detail.className = 'hint';
        detail.textContent = `共享标识：${(group.shared || []).slice(0, 6).join('、')}`;
        block.appendChild(detail);
      }
      content.appendChild(block);
    });

    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKey);
      wrap.remove();
      resolve(value);
    };
    const onKey = (event) => {
      const modals = document.querySelectorAll('.modal');
      if (modals.length && modals[modals.length - 1] !== wrap) return;
      if (event.key === 'Escape') { event.preventDefault(); finish(false); }
    };

    const actions = document.createElement('div');
    actions.className = 'modal-actions';
    const cancel = document.createElement('button');
    cancel.textContent = '取消';
    cancel.onclick = () => finish(false);
    const apply = document.createElement('button');
    apply.className = 'primary';
    apply.textContent = '保留所选并重新生成控制器';
    apply.onclick = async () => {
      apply.disabled = true;
      apply.textContent = '处理中…';
      try {
        const result = await call('resolve_mod_conflicts',
          Array.from(picked.values()).filter(Boolean));
        if (!result || result.ok === false) {
          await showAlert((result && result.message) || '处理失败', '处理失败');
        } else {
          await showAlert(result.message || '已处理冲突', '冲突已处理');
          await refreshFromState();
        }
        finish(result || true);
      } catch (err) {
        apply.disabled = false;
        apply.textContent = '保留所选并重新生成控制器';
        await showAlert(`处理冲突失败：${err}`, '处理失败');
      }
    };
    actions.appendChild(cancel);
    actions.appendChild(apply);
    content.appendChild(actions);

    document.addEventListener('keydown', onKey);
    document.body.appendChild(wrap);
    apply.focus();
  });
}

// ── 异常状态预警弹窗（用户 2026-09-30 要求）─────────────────────────────────
// 与普通弹窗的三点不同，缺一不可：
//   ① **不可关闭** —— 没有关闭按钮、点遮罩不关、Esc 不关，必须三选一；
//   ② **强制停留** holdSeconds 秒（内容由仓库里的 alerts.json 配，默认 10）：倒计时期间
//      所有按钮置灰不可点，读完才放行 —— 防止"看到就顺手点掉"；
//   ③ **三个按钮**，按用户准则把推荐动作放**右侧橙色主按钮 + 默认聚焦**：
//      左「仍然启动」（冒险项）／中「保持配置但不启动」／右「还原配置」（主选）。
// resolve 出 'restore' | 'hold' | 'launch'。
function showAlertGate({
  title,
  message,
  holdSeconds = 10,
  okText = '还原配置',
  extraText = '保持配置但不启动',
  cancelText = '仍然启动',
}) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal';
    wrap.innerHTML = '<div class="modal-content" style="width:min(620px,94vw)">'
      + '<div class="modal-header"><h3></h3></div>'
      + '<pre class="modal-body"></pre>'
      + '<div class="modal-actions"></div></div>';
    wrap.querySelector('h3').textContent = title;
    wrap.querySelector('.modal-body').textContent = message;
    const actions = wrap.querySelector('.modal-actions');
    let settled = false;
    let timer = null;
    let blocked = true;
    const buttons = [];
    const finish = (value) => {
      if (settled || blocked) return;
      settled = true;
      if (timer) clearInterval(timer);
      document.removeEventListener('keydown', onKey, true);
      wrap.remove();
      resolve(value);
    };
    // 只拦自己这一层：多个弹窗叠着时别去影响下面那个（同 showModalDialog 的处理）
    const isTop = () => {
      const modals = document.querySelectorAll('.modal');
      return modals.length > 0 && modals[modals.length - 1] === wrap;
    };
    const onKey = (event) => {
      if (!isTop()) return;
      if (event.key === 'Escape' || (event.key === 'Enter' && blocked)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener('keydown', onKey, true);
    const mk = (label, value, primary) => {
      const btn = document.createElement('button');
      btn.textContent = label;
      if (primary) btn.className = 'primary';
      btn.onclick = () => finish(value);
      actions.appendChild(btn);
      buttons.push({ btn, label });
      return btn;
    };
    mk(cancelText, 'launch', false);        // 左：冒险项
    mk(extraText, 'hold', false);           // 中：什么都不做
    const ok = mk(okText, 'restore', true); // 右：推荐动作（橙色 primary）
    const release = () => {
      blocked = false;
      buttons.forEach(({ btn, label }) => { btn.textContent = label; btn.disabled = false; });
      ok.focus();
    };
    let left = Math.max(0, Math.floor(Number(holdSeconds) || 0));
    if (left > 0) {
      const tick = () => {
        if (left <= 0) { release(); if (timer) clearInterval(timer); return; }
        buttons.forEach(({ btn }) => { btn.disabled = true; });
        ok.textContent = `${okText}（请先阅读，${left} 秒后可选）`;
        left -= 1;
      };
      tick();
      timer = setInterval(tick, 1000);
    } else {
      release();
    }
    document.body.appendChild(wrap);
  });
}

// ── 公告（info/warning）：重大信息发布用，**不锁启动** ───────────────────────
// ⚠ 必须"跟着数据走"：公告是**后端后台线程**拉的（要等首屏就绪 + 一次 IO），
//   实测通常晚于 boot() 里的固定定时器 —— 2026-09-30 出过"后端日志说拿到了 1 条、
//   界面却没弹"（那次只在 boot 里 setTimeout 检查一次，检查时数据还没到）。
//   所以改成每次 refreshFromState() 之后都调一次本函数，内部幂等（弹过的不再弹）。
let __announcementsBusy = false;
const __announcementsShown = new Set();
async function maybeShowAnnouncements() {
  if (__announcementsBusy) return;
  const list = (state.announcements || []).filter((a) => a && a.id && !__announcementsShown.has(a.id));
  if (!list.length) return;
  __announcementsBusy = true;
  try {
    for (const a of list) {
      __announcementsShown.add(a.id);
      const lines = [a.title || '公告', ''];
      if (a.body) lines.push(a.body, '');
      if (a.url) lines.push('详情见下面的链接：');
      // 网址直接点开：不再提供「打开详情」按钮（用户 2026-10-01 要求去掉所有"打开键"）
      await showModalDialog({
        title: '来自作者的公告',
        message: lines.join('\n'),
        link: a.url ? { text: a.url, url: a.url } : null,
        okText: '我知道了',
        showCancel: false,
      });
      // 记已读：同一条公告下次启动不再弹（critical 预警不在此列，它每次都弹）
      try { await call('announcements_seen', [a.id]); } catch (err) { /* 忽略 */ }
    }
    state.announcements = [];
  } catch (err) {
    /* 忽略：公告失败绝不影响使用 */
  } finally {
    __announcementsBusy = false;
  }
}

// ── 文件守护：关键文件被反复删掉（疑似杀毒软件）→ 建议加白名单 ──────────────
// 用户 2026-10-01 要求：「加入对文件的检测，如果某一文件老是被删掉，要在启动的时候
// 出个弹窗提醒用户，建议把某个文件夹加入杀毒软件白名单」；随后明确**挂到「一键启动」**
// 这条流程上（打开管理器时不弹）。判据全在后端 filewatch.py（曾经就位过 + 连续两次
// 启动都缺 + 同组还有别的文件在），这里只负责"弹一次 + 记已提醒"。
// 唯一调用点：runOneClickLaunch() 里、prepare_launch 之前。
let __fileWatchdogBusy = false;
const __fileWatchdogShown = new Set();
async function maybeShowFileWatchdog() {
  if (__fileWatchdogBusy) return;
  const info = state.fileWatchdog;
  if (!info || !(info.items || []).length) return;
  const fresh = info.items.filter((item) => item && item.key && !__fileWatchdogShown.has(item.key));
  if (!fresh.length) return;
  __fileWatchdogBusy = true;
  try {
    const lines = ['这些文件本来是在的，最近连续几次启动却不见了（补上以后又没了）：', ''];
    for (const item of fresh) {
      __fileWatchdogShown.add(item.key);
      lines.push(`· ${item.label}　已缺 ${item.missing || 0} 次`);
    }
    if (info.note) lines.push('', info.note);
    if ((info.dirs || []).length) {
      lines.push('', '建议加入杀毒软件白名单的目录：');
      for (const dir of info.dirs) lines.push(`　${dir}`);
    }
    lines.push('', '加完白名单后，点一次「一键启动」就会自动补回来。');
    const openDir = await showModalDialog({
      title: '有文件被反复删除',
      message: lines.join('\n'),
      okText: '打开目录加白名单',
      cancelText: '知道了',
    });
    if (openDir && (info.dirs || []).length) {
      try { await call('open_path_in_explorer', info.dirs[0]); } catch (err) { /* 忽略 */ }
    }
  } catch (err) {
    /* 忽略：这个提醒坏掉绝不影响使用 */
  } finally {
    // 记已提醒（不管用户点了哪个按钮）：不然每次刷新界面都会再弹一遍
    try { await call('file_watchdog_ack', fresh.map((item) => item.key)); } catch (err) { /* 忽略 */ }
    __fileWatchdogBusy = false;
  }
}

const showAlert = (message, title = '提示') =>
  showModalDialog({ title, message, okText: '知道了', showCancel: false });

const showConfirm = (message, title = '确认操作') =>
  showModalDialog({ title, message, okText: '继续', showCancel: true });

// ── 日志分级（英文等级 + 分色）──────────────────────────────
// 注意：这三个必须是**顶层函数** —— boot() 会调用它们，而 boot 在 bind() 之外。
function detectLogLevel(text) {
  if (/\[(ERROR|ERR|FATAL)\]/i.test(text) || /✗/.test(text)) return 'error';
  if (/\[(WARN|WARNING)\]/i.test(text) || /⚠/.test(text)) return 'warn';
  if (/\[(DEBUG|TRACE)\]/i.test(text)) return 'debug';
  if (/\[(OK|SUCCESS)\]/i.test(text) || /✓/.test(text)) return 'ok';
  return 'info';
}
function appendLogLine(el, text) {
  const level = detectLogLevel(text);
  const span = document.createElement('span');
  span.className = `log-line log-${level}`;
  span.textContent = text + '\n';
  el.appendChild(span);
}
function logLine(text) {
  const el = $('console-log');
  if (!el) return;
  if (el.dataset.ready !== '1') { el.textContent = ''; el.dataset.ready = '1'; }
  const ts = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  appendLogLine(el, `[${ts}] ${text}`);
  el.scrollTop = el.scrollHeight;
}
function paintLog(el) {
  if (!el) return;
  const raw = el.textContent;
  if (!raw || el.dataset.painted === '1') return;
  el.textContent = '';
  raw.split('\n').forEach((line) => {
    if (line.trim()) appendLogLine(el, line);
  });
  el.dataset.painted = '1';
}
function showTab(name, persist = true) {
  const panels = Array.from(document.querySelectorAll('.panel'));
  // 兜底：name 匹配不到任何面板时（例如配置里存着旧的 tab 名），回退到第一个，
  // 否则所有面板都会被摘掉 active → 整个内容区空白
  let target = name;
  if (!panels.some(p => p.id === 'tab-' + target)) {
    const fallback = panels[0];
    target = fallback ? fallback.id.replace(/^tab-/, '') : target;
  }
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === target));
  panels.forEach(p => p.classList.toggle('active', p.id === 'tab-' + target));
  if (persist && window.pywebview && window.pywebview.api) {
    call('save_config', { last_tab: target }).catch(() => {});
  }
}

async function call(method, ...args) {
  if (!window.pywebview || !window.pywebview.api) throw new Error('PyWebview API is not ready');
  try {
    return await window.pywebview.api[method](...args);
  } catch (err) {
    const message = err && err.message ? err.message : String(err);
    await showAlert(`${method} failed:
${message}`);
    throw err;
  }
}

function sanitizeSelection() {
  const byId = new Map(state.mods.map(mod => [mod.id, mod]));
  const seen = new Set();
  const next = new Set();
  for (const id of state.selected) {
    const mod = byId.get(id);
    if (!mod) continue;
    if (mod.kind === 'character' || mod.kind === 'unknown') {
      const key = mod.conflict_group || mod.group;
      if (seen.has(key)) continue;
      seen.add(key);
    }
    next.add(id);
  }
  state.selected = next;
}

function renderMods() {
  const root = $('mod-list');
  root.innerHTML = '';
  const groups = {};
  for (const mod of state.mods) {
    // 依赖项（_deps 分组 / kind=dependency|tool）不占 Mod 列表位置：
    // 它们是别人依赖的公共资源，由依赖页统一管理
    const groupName = String(mod.conflict_group || mod.group || '');
    if (groupName === '_deps' || mod.kind === 'dependency') continue;
    // **辅助 Mod 不在这里显示**（用户 2026-10-01 方案④）：它们不属于任何角色，
    // 单独在「辅助 Mod」页管理，免得混进角色分组里、还被要求确认归属。
    if (mod.kind === 'assist') continue;
    const key = mod.conflict_group || mod.group || '未分类';
    (groups[key] ||= []).push(mod);
  }
  const groupNames = Object.keys(groups).sort((a, b) => String(a).localeCompare(String(b), 'zh-Hans-CN'));
  for (const group of groupNames) {
    const mods = groups[group];
    const enabledCount = mods.filter(m => m.kind === 'dependency' || m.kind === 'tool' || state.selected.has(m.id)).length;
    const block = document.createElement('section');
    block.className = 'group-block';
    block.innerHTML = `
      <div class="group-header">
        <h3>${escapeHtml(group)}</h3>
        <span class="hint">${mods.length} 个 Mod · 已启用 ${enabledCount}</span>
      </div>
    `;
    const grid = document.createElement('div');
    grid.className = 'mod-list';
    for (const mod of mods) {
      const dependency = mod.kind === 'dependency' || mod.kind === 'tool';
      // 角色识别不确定时（low/none）在卡片上打个标记，点它就能选择。
      // 用户 2026-10-01 要求「对没法完全确定归属的 Mod 进行**预识别**（匹配与哪个角色
      // 相关字数最多）」，但**黄字照旧显示** —— 预识别只是把下拉预选上，仍需用户点一下。
      const needConfirm = !dependency && (mod.char_confidence === 'low' || mod.char_confidence === 'none');
      const guess = (mod.char_guess || '').trim();
      const card = document.createElement('div');
      card.className = 'mod-card' + (dependency ? ' disabled' : '');
      const checked = dependency || state.selected.has(mod.id);
      card.innerHTML = `
        <div class="cover" data-cover-box="${escapeHtml(mod.id)}"><span>无预览图</span></div>
        <div class="name">${escapeHtml(mod.name)}</div>
        <div class="meta">${escapeHtml(mod.kind)} · id=${escapeHtml(mod.id)}</div>
        ${needConfirm ? '<div class="meta" style="color:#d98a1f;cursor:pointer" data-char-pick="' + escapeHtml(mod.id) + '">⚠ 角色待确认'
          + (guess ? `（预识别：${escapeHtml(guess)}）` : '') + ' —— 点此选择</div>' : ''}
        ${mod.fixed ? '<div class="fixed-tag">✓ 已修复过（可在「⋯」里回滚）</div>' : ''}
        ${mod.duplicate_of ? '<div class="meta" style="color:#d98a1f">⚠ 与「' + escapeHtml(mod.duplicate_of) + '」内容相同（重复副本）</div>' : ''}
        <label class="switch">
          <input type="checkbox" data-mod-toggle value="${escapeHtml(mod.id)}" ${checked ? 'checked' : ''} ${dependency ? 'disabled' : ''}>
          <span class="slider"></span>
        </label>
        <button class="mod-more" data-mod-more="${escapeHtml(mod.id)}" title="更多：修复（实验性）/ 回滚 / 移出库">⋯</button>
      `;
      grid.appendChild(card);
    }
    block.appendChild(grid);
    root.appendChild(block);
  }
  root.querySelectorAll('input[data-mod-toggle]').forEach(cb => {
    cb.onchange = async () => {
      const mod = state.mods.find(item => item.id === cb.value);
      if (!mod) return;
      const groupKey = mod.conflict_group || mod.group;
      // 「强行关闭角色 Mod 互斥」打开时：只增删自己，**不再**取消同角色的其它 Mod
      // （用户 2026-10-01 要求：便于部分同角色但不冲突的 Mod）
      const allowSame = state.config.allow_same_character_mods === true;
      if (cb.checked) {
        state.selected.add(mod.id);
        if (!allowSame) {
          for (const other of state.mods) {
            if (other.id === mod.id) continue;
            if (other.kind !== 'character') continue;
            if ((other.conflict_group || other.group) !== groupKey) continue;
            state.selected.delete(other.id);
            const otherToggle = root.querySelector(`input[data-mod-toggle][value="${CSS.escape(other.id)}"]`);
            if (otherToggle) otherToggle.checked = false;
          }
        }
      } else {
        state.selected.delete(mod.id);
      }
      updateGroupHeader(cb.closest('.group-block'), groupKey);
      saveSelection();
    };
  });
  // 卡片右下角「⋯」：**鼠标移上去就出就地菜单**（用户要求：放上去就要出工具栏，不是点击才出）
  root.querySelectorAll('button[data-mod-more]').forEach(btn => {
    const open = () => {
      cancelModMenuClose();
      openModMenu(btn.dataset.modMore, btn);
    };
    btn.onmouseenter = open;
    btn.onclick = (event) => {          // 触摸屏 / 键盘也能用
      event.preventDefault();
      event.stopPropagation();
      open();
    };
    btn.onmouseleave = () => scheduleModMenuClose();
  });
  $('library-status').textContent = `已发现 ${state.mods.length} 个 Mod，按角色分组显示`;
  // 修复工具就位的状态**不再占版面**（用户 2026-10-01 要求去掉库页那段说明）：
  // 只在「⋯」菜单里体现 —— 工具没就位时「修复」按钮置灰，悬停能看到该放哪。
  call('modfix_status').then((r) => { state.modfixTool = (r && r.tool) || {}; }).catch(() => {});
  loadCovers();
  renderAssist();      // 辅助 Mod 页跟着一起刷新（它不参与上面的角色分组）
}

// ── 辅助 Mod 页（用户 2026-10-01 方案④：「给这种非皮肤小 mod 留加载通道」）──
// 这类包（隐藏 UI / 改界面 / 小工具）不换装、不属于任何角色，所以：
//   · 不进角色分组、不参与同角色互斥（后端 conflict_group 用自身路径）；
//   · 不弹"确认角色归属"（后端直接给 high 置信度）；
//   · 单独一页列出来，开关即启用（勾选后照常被 stage 进 Mods、由 EFMI 加载）。
function renderAssist() {
  const root = $('assist-list');
  if (!root) return;
  const assistMods = state.mods.filter(m => m.kind === 'assist');
  const status = $('assist-status');
  root.innerHTML = '';
  if (!assistMods.length) {
    if (status) status.textContent = `当前没有辅助 Mod（共扫到 ${state.mods.length} 个 Mod）`;
    root.innerHTML = '<p class="hint">还没有辅助 Mod。<br>'
      + '· 把这类小包（隐藏 UI / 改界面 / 小工具）<b>拖到页面任意处</b>导入，或放进 Mod 库后点「重新扫描」；<br>'
      + '· 自动识别条件：<b>没有换装资源</b>（无 Meshes/Textures）+（名字含「隐藏/辅助/UI/HUD/水印」或 ini 是 <code>handling = skip</code>）+ <b>归不到任何角色</b>；<br>'
      + '· 也可以在任何 Mod 卡片的「⋯」里手动「<b>标记为辅助 Mod</b>」。</p>';
    return;
  }
  const enabled = assistMods.filter(m => state.selected.has(m.id)).length;
  if (status) status.textContent = `辅助 Mod ${assistMods.length} 个 · 已启用 ${enabled} · 与角色 Mod 互不影响`;
  const grid = document.createElement('div');
  grid.className = 'mod-list';
  for (const mod of assistMods) {
    const checked = state.selected.has(mod.id);
    const actionCount = (mod.actions || []).length;
    const card = document.createElement('div');
    card.className = 'mod-card';
    card.innerHTML = `
      <div class="cover" data-cover-box="${escapeHtml(mod.id)}"><span>无预览图</span></div>
      <div class="name">${escapeHtml(mod.name)}</div>
      <div class="meta">辅助 Mod · 可调动作 ${actionCount} 个${mod.fixed ? ' · 已修复过' : ''}${mod.duplicate_of ? ` · ⚠ 与「${escapeHtml(mod.duplicate_of)}」内容相同（重复副本）` : ''}</div>
      <label class="switch">
        <input type="checkbox" data-assist-toggle value="${escapeHtml(mod.id)}" ${checked ? 'checked' : ''}>
        <span class="slider"></span>
      </label>
      <button class="mod-more" data-mod-more="${escapeHtml(mod.id)}" title="更多：更换归属 / 标记 / 修复 / 移出库">⋯</button>
    `;
    grid.appendChild(card);
  }
  root.appendChild(grid);

  root.querySelectorAll('input[data-assist-toggle]').forEach(cb => {
    cb.onchange = () => {
      // 只增删自己：辅助 Mod 之间、以及与角色 Mod 之间都不互斥
      if (cb.checked) state.selected.add(cb.value); else state.selected.delete(cb.value);
      saveSelection();
      renderAssist();
    };
  });
  root.querySelectorAll('button[data-mod-more]').forEach(btn => {
    const open = () => { cancelModMenuClose(); openModMenu(btn.dataset.modMore, btn); };
    btn.onmouseenter = open;
    btn.onclick = (event) => { event.preventDefault(); event.stopPropagation(); open(); };
    btn.onmouseleave = () => scheduleModMenuClose();
  });
  loadCovers();
}

// 手动改标记（自动识别认错了就在这里救回来）：角色 Mod ⇄ 辅助 Mod
async function markModKind(modId, name, kind) {
  const result = await call('set_mod_kind', modId, kind);
  if (!result || result.ok === false) {
    await showAlert((result && result.message) || '标记失败', '标记失败');
    return;
  }
  setStatus(kind === 'assist' ? `已把「${name}」标记为辅助 Mod` : `已把「${name}」标记为角色 Mod`);
  await scan();       // 重扫一遍，让它出现在对应的页里
}

// ── Mod 卡片「⋯」：就地弹出的小菜单（修复 / 回滚 / 打开目录 / 移出库） ──────
// 用户要求：**放上去出菜单，而不是出个弹窗**。菜单贴在按钮右下角，点空白/Esc/滚动收起。
// 修复流程见后端 modfix.py：临时目录里跑社区工具（不在库/Mods 里留备份与日志）、
// 改前整份备份、可单独回滚。工具来自 B站 up 主 可可HXL（v1.5，不开源、实验性）。
function closeModMenus() {
  clearTimeout(__modMenuTimer);
  document.querySelectorAll('.mod-menu').forEach(el => el.remove());
}

// 鼠标从按钮挪到菜单上时会短暂离开按钮 —— 延时收起，避免"手一抖菜单就没了"
let __modMenuTimer = null;
function scheduleModMenuClose(delay = 220) {
  clearTimeout(__modMenuTimer);
  __modMenuTimer = setTimeout(() => closeModMenus(), delay);
}
function cancelModMenuClose() {
  clearTimeout(__modMenuTimer);
}

function openModMenu(modId, anchorEl) {
  const existing = document.querySelector('.mod-menu');
  if (existing && existing.dataset.modMenu === modId) return;   // 已经是这个菜单，别重建（否则 hover 时闪）
  closeModMenus();
  const mod = state.mods.find(item => item.id === modId);
  if (!mod) return;

  const menu = document.createElement('div');
  menu.className = 'mod-menu';
  menu.dataset.modMenu = modId;
  const tags = [];
  if (mod.fixed) tags.push('已修复过');
  if (mod.can_rollback) tags.push('可回滚');
  const isAssist = mod.kind === 'assist';
  if (isAssist) tags.push('辅助 Mod');
  // 注意：**不要因为"工具还没展开到 runtime\modfix"就把「修复」置灰**（2026-10-01 用户
  // 反馈「为什么现在更多中修复点不了」）—— 随包 assets\modfix 里那份一直都在，点下去会
  // 自动展开。只有"随包也没有、runtime 也没有"时才在点击时说明原因。
  menu.innerHTML = `
    <div class="mod-menu-head">归属：${escapeHtml(mod.group || '未分类')}${tags.length ? ' · ' + escapeHtml(tags.join(' · ')) : ''}</div>
    <button data-act="assign">更换 Mod 归属…</button>
    <button data-act="${isAssist ? 'mark-character' : 'mark-assist'}">${isAssist ? '标记为角色 Mod' : '标记为辅助 Mod'}</button>
    <button data-act="fix">修复（实验性）</button>
    <button data-act="rollback" ${mod.can_rollback ? '' : 'disabled'}>回滚修复</button>
    <button data-act="open">打开所在文件夹</button>
    <button data-act="delete">移出 Mod 库</button>
  `;
  document.body.appendChild(menu);
  // 鼠标停在菜单上时不要收起（从按钮移到菜单中间有个缝）
  menu.onmouseenter = cancelModMenuClose;
  menu.onmouseleave = () => scheduleModMenuClose();

  // 贴着按钮放：默认向右下展开，贴到窗口边缘就往上/往左收
  const rect = anchorEl.getBoundingClientRect();
  const width = menu.offsetWidth || 172;
  const height = menu.offsetHeight || 150;
  let left = rect.right - width;
  if (left < 8) left = 8;
  if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8;
  let top = rect.bottom + 6;
  if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 6);
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;

  menu.querySelectorAll('button').forEach(btn => {
    btn.onclick = (event) => {
      event.stopPropagation();
      const act = btn.dataset.act;
      closeModMenus();
      if (act === 'open') { call('open_path_in_explorer', mod.path || ''); return; }
      if (act === 'assign') return openCharacterAssign(modId, mod.name, mod.group || '');
      if (act === 'mark-assist') return markModKind(modId, mod.name, 'assist');
      if (act === 'mark-character') return markModKind(modId, mod.name, 'character');
      if (act === 'fix') return doFixMod(modId, mod.name);
      if (act === 'rollback') return doRollbackMod(modId, mod.name);
      if (act === 'delete') return doDeleteMod(modId, mod.name);
    };
  });
}

// 点空白 / 按 Esc / 滚动 → 收起（只注册一次）
document.addEventListener('click', (event) => {
  if (event.target.closest('.mod-menu') || event.target.closest('[data-mod-more]')) return;
  closeModMenus();
});
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModMenus(); });
window.addEventListener('scroll', () => closeModMenus(), true);

async function doFixMod(modId, name) {
  // 只有"随包也没有、runtime 也没有"时才拦（正常情况随包 assets\modfix 里一直有）
  const tool = state.modfixTool || {};
  if (tool.usable === false) {
    await showAlert('没找到 Mod 修复工具，所以现在修不了：\n'
      + '· 正常情况下它随包放在 assets\\modfix\\，启动时会自动展开\n'
      + '· 也可以手动把 exe 放到 <数据根>\\runtime\\modfix\\\n'
      + '· 从 Release 下载的话，重新展开一次 assets-bundle.zip 即可', '修复工具未就位');
    return;
  }
  if (!await showModalDialog({
    title: '修复这个 Mod（实验性）',
    message: '会把 ini 里的资源槽位号适配当前游戏版本：\n'
      + '· 先在临时目录里跑工具，不会在 Mod 库或 Mods 里留下备份与日志\n'
      + '· 修复前会「整份备份」这个 Mod，随时能回滚\n'
      + '· 工具来自 B站 up 主 可可HXL（v1.5），它不开源、判据未经完整验证\n\n继续修复？',
    okText: '开始修复', cancelText: '先不修',
  })) return;
  setStatus('正在修复…');
  const r = await call('fix_mod', modId);
  for (const line of (r.tool_log || [])) logLine(`修复工具: ${line}`);
  logLine(r.ok
    ? (r.skipped ? `已跳过: ${r.message}`
      : `修复完成: 改动 ${r.changed_count} 个文件${r.marked ? '（已带修复标记）' : '（没匹配到需修的内容）'}`)
    : `✗ 修复失败: ${r.message || '未知错误'}`);
  setStatus(r.ok ? '修复完成' : `修复失败: ${r.message || ''}`);
  await refreshFromState();
}

async function doRollbackMod(modId, name) {
  if (!await showModalDialog({
    title: '回滚这个 Mod 的修复',
    message: `会用最近一次修复前的备份还原「${name}」：\n`
      + '· 还原后这个 Mod 回到修复之前的状态\n'
      + '· 备份用过一次就会被清掉（每个 Mod 最多留 3 份）\n\n继续？',
    okText: '回滚', cancelText: '算了',
  })) return;
  const r = await call('rollback_mod', modId);
  logLine(r.ok
    ? `已回滚: 还原 ${(r.changed || []).length} 项（备份时间 ${r.restored_from}）`
    : `✗ 回滚失败: ${r.message}`);
  setStatus(r.ok ? '已回滚' : `回滚失败: ${r.message || ''}`);
  await refreshFromState();
}

async function doDeleteMod(modId, name) {
  if (!await showModalDialog({
    title: '把这个 Mod 移出库',
    message: `「${name}」会从 Mod 库里移走（不是真删）：\n`
      + '· 移到 runtime\\backups\\mod-trash\\<时间戳>\\，需要时可自己拿回来\n'
      + '· 勾选里也会一并去掉\n\n继续？',
    okText: '移出库', cancelText: '算了',
  })) return;
  const r = await call('delete_mod', modId);
  logLine(r.ok ? `已移出库: ${r.moved_to}` : `✗ 移出失败: ${r.message}`);
  setStatus(r.ok ? '已移出 Mod 库' : `移出失败: ${r.message || ''}`);
  await refreshFromState();
}

// ── 「⋯」→ 更换 Mod 归属 ───────────────────────────────────────────────────
// 用户 2026-10-01 要求：「更多中加一项**更换 Mod 归属**」。识别的结果会写进该 Mod 的
// mod.meta.json（和"角色待确认"那条链路同一个后端接口），卡片分组与同角色互斥随之改变。
async function openCharacterAssign(modId, name, current) {
  const modal = $('char-assign-modal');
  const select = $('char-assign-select');
  if (!modal || !select) return;
  let known = [];
  try {
    known = (await call('known_characters')) || [];
  } catch (err) {
    known = [];      // 后端忙也不挡住手工选择：至少能选回当前值
  }
  // 当前归属也列进去（可能是用户自定义的分组名，不在标准角色表里）
  const options = [...new Set([...(current ? [current] : []), ...known])].filter(Boolean);
  select.innerHTML = options
    .map((n) => `<option value="${escapeHtml(n)}"${n === current ? ' selected' : ''}>${escapeHtml(n)}</option>`)
    .join('');
  $('char-assign-name').textContent = name || '';
  $('char-assign-current').textContent = current || '未分类';
  modal.classList.remove('hidden');

  $('char-assign-cancel').onclick = () => modal.classList.add('hidden');
  $('char-assign-save').onclick = async () => {
    const value = (select.value || '').trim();
    if (!value) {
      await showAlert('请先选择一个角色。', '更换 Mod 归属');
      return;
    }
    try {
      const r = await call('set_mod_character', modId, value);
      if (!r || !r.ok) {
        await showAlert((r && r.message) || '保存失败', '更换 Mod 归属');
        return;
      }
      modal.classList.add('hidden');
      logLine(`已更换归属: ${name} → ${value}`);
      setStatus(`已把「${name}」归到「${value}」`);
      await scan();
      await refreshFromState();
    } catch (err) {
      await showAlert(`保存失败：${err.message || err}`, '更换 Mod 归属');
    }
  };
}

function updateGroupHeader(block, groupKey) {  if (!block) return;
  const mods = state.mods.filter(m => (m.conflict_group || m.group) === groupKey);
  const enabledCount = mods.filter(m => m.kind === 'dependency' || m.kind === 'tool' || state.selected.has(m.id)).length;
  const hint = block.querySelector('.group-header .hint');
  if (hint) hint.textContent = `${mods.length} 个 Mod · 已启用 ${enabledCount}`;
}

let selectionSaveTimer = null;
async function saveSelection() {
  clearTimeout(selectionSaveTimer);
  const ids = Array.from(state.selected);
  state.config.selected_mods = ids;
  await call('save_config', { selected_mods: ids });
}

async function loadCovers() {
  const boxes = document.querySelectorAll('[data-cover-box]');
  for (const box of boxes) {
    const id = box.dataset.coverBox;
    try {
      const result = await call('get_mod_cover', id);
      if (result.ok) {
        const img = document.createElement('img');
        img.alt = 'cover';
        img.src = result.data_uri;
        box.innerHTML = '';
        box.appendChild(img);
      }
    } catch (err) {
      // ignore cover errors
    }
  }
}

// 这些行属于"自动换线路的中间过程"，不是失败 —— 不要当错误显示给用户
function isNoisyLine(line) {
  return /^尝试线路：/.test(line)
    || /^线路 .*? 失败：/.test(line)
    || /^直连不通，/.test(line);
}

function renderDependencies() {
  const root = $('dep-list');
  root.innerHTML = '';
  const report = state.dependency_report || {};
  const entries = Object.entries(report.manifest || {});
  // 「本管理器」置顶（后端已放第一个，这里再兜一层，避免别处合并时被挤下去）
  entries.sort((a, b) => (b[1].is_app ? 1 : 0) - (a[1].is_app ? 1 : 0));
  for (const [key, item] of entries) {
    const node = document.createElement('div');
    node.className = 'dep-item' + (item.is_app ? ' dep-app' : '');
    const status = item.status || (item.present ? '已安装' : '缺失');
    const statusClass = item.present ? 'ok' : ((item.needed || item.required) ? 'missing' : 'skip');
    const updateBtn = (item.is_app && item.update_available)
      ? `<button class="primary" data-app-update>更新到 v${escapeHtml(item.latest || '')}</button>` : '';
    node.innerHTML = `
      <div>
        <div>${escapeHtml(item.display || key)}</div>
        <div class="meta hint">${escapeHtml(item.source || '')}${item.install_dir ? ' · ' + escapeHtml(item.install_dir) : ''}</div>
      </div>
      <div class="dep-right">
        <div class="${statusClass}">${escapeHtml(status)}</div>
        ${updateBtn}
      </div>
    `;
    const button = node.querySelector('[data-app-update]');
    if (button) button.onclick = (event) => { event.preventDefault(); startAppUpdateFromDep(); };
    root.appendChild(node);
  }
  if (!entries.length) root.innerHTML = '<div class="hint">未加载依赖清单</div>';
  $('dep-status').textContent = `已识别依赖：${(report.required || []).join(', ') || '无'}`;
}

// 用户要求：点自更新之后切到依赖页，并在那条依赖上显示进度条
async function startAppUpdateFromDep() {
  showTab('dependencies');
  $('dep-progress').value = 0;
  $('dep-progress-text').textContent =
    '正在更新管理器…（更新期间请不要手动打开程序，替换完成后会自动重启）';
  $('dep-results').textContent = '';
  setStatus('正在更新程序…（请勿手动打开程序）');
  try {
    await call('start_app_update');
  } catch (err) {
    setStatus(`更新请求失败: ${err.message || err}`);
    return;
  }
  await pollDependencyProgress($('dep-results'));
}

// ── Mod 库：把 zip 直接拖进来 ────────────────────────────────────────────────
// 用户需求：「如果在 Mod 库界面，能直接拖 zip 进去，然后自动解压，解析角色归属」。
// pywebview 拿不到拖放文件的本地路径（WebView2 沙箱里 File.path 不可用），所以这里
// 读成 ArrayBuffer 再转 base64 交给后端解压；后端复用既有的收编 + 角色归属链路。
function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunk = 0x8000;                       // 分块拼接，避免 apply 参数过多导致栈溢出
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

// ── 拖入导入 ────────────────────────────────────────────────────────────────
// 用户要求：去掉原来那个小方块拖放区，改成**整页**都能拖（仅 Mod 库页生效），
// 并且拖进窗口还没松手时要有明显提示 —— 否则用户会以为"拖了没反应"。
let dragDepth = 0;
let dropBusy = false;

function libraryTabActive() {
  const tab = $('tab-library');
  return !!tab && tab.classList.contains('active');
}

function setDropHint(on, text) {
  const hint = $('drop-hint');
  if (!hint) return;
  const label = $('drop-hint-msg');
  if (label && text) label.textContent = text;
  hint.classList.toggle('hidden', !on);
}

function dragHasFiles(event) {
  const types = event.dataTransfer && event.dataTransfer.types;
  return !!types && Array.prototype.indexOf.call(types, 'Files') >= 0;
}

async function importDroppedFile(file) {
  if (!file) return;
  if (!/\.(zip|7z|rar)$/i.test(file.name)) {
    await showAlert('目前只支持 .zip / .7z / .rar 压缩包（其他格式请先解压再拖进来）。', '导入 Mod');
    return;
  }
  dropBusy = true;
  // **松开鼠标就收起提示层**（用户要求：「应该是释放就消失」）。提示层的职责只是
  // "拖进来时告诉你松手即可导入" —— 之后的进度改在**状态栏**显示。否则它会一直挂在
  // 屏幕上、还可能盖住结果弹窗，看起来就像卡死（2026-10-01 实测）。
  setDropHint(false);
  setStatus(`正在读取 ${file.name} …`);
  try {
    // **分块上传**：pywebview 的 js_api 参数走 WebView2 消息通道，一次性把整包的 base64
    // 丢过去会先卡住再闪退（2026-10-01 用户实测：「拖 zip 进去会卡在解压和识别角色，
    // 然后闪退」）。改成每块 1 MB 逐块传，进度显示在状态栏。
    const begin = await call('import_mod_begin', file.name);
    if (!begin.ok) {
      await showAlert(begin.message || '导入失败', '导入 Mod');
      return;
    }
    const bytes = new Uint8Array(await file.arrayBuffer());
    const CHUNK = 1024 * 1024;
    let sent = 0;
    while (sent < bytes.length) {
      const end = Math.min(sent + CHUNK, bytes.length);
      const slice = bytes.slice(sent, end);
      const part = await call('import_mod_chunk', begin.token, arrayBufferToBase64(slice.buffer));
      if (!part.ok) {
        await showAlert(part.message || '传输失败', '导入 Mod');
        return;
      }
      sent = end;
      const pct = Math.floor(sent * 100 / Math.max(bytes.length, 1));
      setStatus(`正在上传 ${file.name}：${pct}%（${(sent / 1048576).toFixed(1)} MB）`);
    }
    setStatus(`正在解压并识别角色：${file.name} …`);
    const result = await call('import_mod_finish', begin.token);
    dropBusy = false;
    if (!result.ok) {
      await showAlert(result.message || '导入失败', '导入 Mod');
    } else {
      try { await scan(); } catch (err) { /* 扫描失败不影响导入结果 */ }
      try { await refreshFromState(); } catch (err) { /* 同上 */ }
      if (result.need_confirm && result.mod_id) {
        // **识别不出来就直接把角色确认窗弹出来**（用户 2026-10-01 反馈：「一个不能确定
        // 角色名字的 mod 拖进去不会弹出角色确定窗」）。以前这里只弹一句"请点确认角色归属
        // 按钮"，用户还得自己回列表找那个 Mod —— 现在拖完立刻让他选。
        setStatus(`「${result.name}」的角色归属不确定，请选择角色`);
        await startCharacterCheck(result.mod_id);
      } else if (result.group && result.mod_id) {
        await showAlert(`已导入「${result.name}」，识别为「${result.group}」。`, '导入 Mod');
      } else if (result.mod_id) {
        await showAlert(`已导入「${result.name}」。`, '导入 Mod');
      } else {
        await showAlert(result.warning || `已解压到 Mod 库，但没有识别出 Mod。`, '导入 Mod');
      }
    }
  } catch (err) {
    await showAlert(`导入失败：${err.message || err}`, '导入 Mod');
  } finally {
    dropBusy = false;
    setDropHint(false);
  }
}

function initDragImport() {
  document.addEventListener('dragenter', (event) => {
    if (!dragHasFiles(event) || !libraryTabActive() || dropBusy) return;
    event.preventDefault();
    dragDepth += 1;
    setDropHint(true, '松开即可导入 Mod');
  });
  // dragover 必须 preventDefault，否则浏览器不会派发 drop 事件
  document.addEventListener('dragover', (event) => {
    if (!dragHasFiles(event) || !libraryTabActive() || dropBusy) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
  });
  document.addEventListener('dragleave', (event) => {
    if (!dragHasFiles(event) || !libraryTabActive()) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0 && !dropBusy) setDropHint(false);
  });
  // 拖出窗口 / 按 Esc 取消时的兜底收起
  window.addEventListener('dragend', () => {
    dragDepth = 0;
    if (!dropBusy) setDropHint(false);
  });
  document.addEventListener('drop', async (event) => {
    dragDepth = 0;
    if (!dragHasFiles(event)) return;
    event.preventDefault();               // 别让 WebView 自己去打开这个文件
    if (dropBusy) return;
    setDropHint(false);
    if (!libraryTabActive()) return;      // 只有 Mod 库页才处理导入
    const file = event.dataTransfer.files && event.dataTransfer.files[0];
    await importDroppedFile(file);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initDragImport);
} else {
  initDragImport();
}

async function scan() {
  setStatus('扫描中...');
  const result = await call('scan');
  state.mods = result.mods || [];
  sanitizeSelection();
  state.dependency_report = result.dependency_report || {};
  renderMods();
  renderDependencies();
  setStatus('扫描完成');
}

async function prepare() {
  setStatus('生成控制器中...');
  state.lastPrepare = await call('prepare', Array.from(state.selected));
  // "不要动用户的 Mod 库"（2026-10-01 硬规则）：staging 与库重叠时后端会**拒绝执行**
  // 并回 blocked —— 这里要把原因原样说给用户（否则只会看到"动作 0 个"摸不着头脑）。
  if (state.lastPrepare && state.lastPrepare.ok === false) {
    $('launch-status').textContent = JSON.stringify(state.lastPrepare, null, 2);
    setStatus('已拒绝生成控制器（保护你的 Mod 库）');
    await showAlert(state.lastPrepare.message || '已拒绝执行：这会动到你的 Mod 库。', '保护 Mod 库');
    const s0 = await call('get_state');
    refreshPaths(s0.config);
    return;
  }
  $('launch-status').textContent = JSON.stringify(state.lastPrepare, null, 2);
  setStatus(`控制器已生成，动作 ${state.lastPrepare.action_count} 个`);
  const s = await call('get_state');
  refreshPaths(s.config);
}

async function refreshPaths(config) {
  state.config = config;
  $('path-controller').textContent = config ? '' : '';
  const info = await call('log');
  $('path-controller').textContent = info.controller;
  $('path-reshade').textContent = info.reshade;
  $('path-staging').textContent = info.staging;
  $('cfg-library_dir').value = config.library_dir || '';
  // Mod 备份目录（用户 2026-10-02 要求「在设置里能自行选择备份目录」）：
  // 留空 = 主路径下的 mod-backup；填的值原样回显，方便他改到别的盘。
  if ($('cfg-mod_backup_dir')) $('cfg-mod_backup_dir').value = config.mod_backup_dir || '';
  // 「Mod 备份」总开关（用户 2026-10-02：「默认开，关了就不备份」）
  if ($('cfg-mod-backup-enabled')) $('cfg-mod-backup-enabled').checked = config.mod_backup_enabled !== false;
  $('cfg-staging_mods_dir').value = config.staging_mods_dir || '';
  $('cfg-runtime_dir').value = config.runtime_dir || '';
  $('cfg-xxmi_launcher').value = config.xxmi_launcher || '';
  $('cfg-migoto_loader').value = config.migoto_loader || '';
  $('cfg-official_launcher').value = config.official_launcher || '';
  $('cfg-game_exe').value = config.game_exe || '';
  $('cfg-reshade_dll').value = config.reshade_dll || '';
  if ($('cfg-dlss5_dir')) $('cfg-dlss5_dir').value = config.dlss5_dir || '';
  if ($('cfg-secondary_motion_dir')) $('cfg-secondary_motion_dir').value = config.secondary_motion_dir || '';
  if ($('cfg-poser_dir')) $('cfg-poser_dir').value = config.poser_dir || '';
  $('cfg-reshade_injection').value = config.reshade_injection || 'xxmi_extra';
  $('cfg-theme').value = config.theme === 'light' ? 'light' : 'dark';
  applyTheme(config.theme === 'light' ? 'light' : 'dark');
  $('cfg-dependency_manifest').value = config.dependency_manifest || '';
  $('cfg-use_builtin_runtime').checked = config.use_builtin_runtime !== false;
  $('cfg-auto_update_dependencies').checked = !!config.auto_update_dependencies;
  $('cfg-require_admin').checked = !!config.require_admin;
  // 「游戏自带 DLSS 时自动停用喂帧组件」——默认开启（config 缺字段时按 true 显示）
  if ($('cfg-auto-disable-feed')) {
    $('cfg-auto-disable-feed').checked = config.auto_disable_feed_on_native_dlss !== false;
  }
  if ($('cfg-download_boost')) $('cfg-download_boost').value = config.download_boost || 'auto';
  if ($('cfg-download_line')) $('cfg-download_line').value = config.download_line || 'auto';
  // 「依赖优先用内部那份」（RabbitFX 等）：默认开 —— config 缺字段时按 true 显示
  if ($('cfg-prefer-internal-deps')) {
    $('cfg-prefer-internal-deps').checked = config.prefer_internal_dependencies !== false;
  }
  refreshDownloadStatus();
}

// 下载加速状态：平时是关的，只在下载慢/抖动时临时开，下完立刻放掉
async function refreshDownloadStatus() {
  const el = $('download-status');
  if (!el) return;
  try {
    const s = await call('get_download_settings');
    const last = (s.status || {}).last;
    const parts = [];
    if (last) {
      parts.push(`上次下载：${last.line || '?'}  ${(last.mbps || 0).toFixed(2)} MB/s`
        + (last.boosted ? `（临时并发 ${last.threads} 连接，已关闭）` : '（单连接，未启用加速）'));
      if (last.bytes) parts.push(`${(last.bytes / 1048576).toFixed(1)} MB / ${(last.seconds || 0).toFixed(0)}s`);
    } else {
      parts.push('还没下载过（加速平时是关的，慢的时候才临时打开）');
    }
    const known = (s.lines || []).filter((l) => l.ok !== null)
      .map((l) => `${l.line}=${(l.mbps || 0).toFixed(2)}`).join('  ');
    if (known) parts.push(`线路记录(MB/s)：${known}`);
    el.textContent = parts.join('　｜　');
  } catch (err) {
    el.textContent = '下载状态读取失败';
  }
}

async function saveConfig() {
  const data = {
    library_dir: $('cfg-library_dir').value.trim(),
    staging_mods_dir: $('cfg-staging_mods_dir').value.trim(),
    runtime_dir: $('cfg-runtime_dir').value.trim(),
    xxmi_launcher: $('cfg-xxmi_launcher').value.trim(),
    migoto_loader: $('cfg-migoto_loader').value.trim(),
    official_launcher: $('cfg-official_launcher').value.trim(),
    game_exe: $('cfg-game_exe').value.trim(),
    reshade_dll: $('cfg-reshade_dll').value.trim(),
    dlss5_dir: $('cfg-dlss5_dir') ? $('cfg-dlss5_dir').value.trim() : '',
    secondary_motion_dir: $('cfg-secondary_motion_dir') ? $('cfg-secondary_motion_dir').value.trim() : '',
    poser_dir: $('cfg-poser_dir') ? $('cfg-poser_dir').value.trim() : '',
    reshade_injection: $('cfg-reshade_injection').value,
    theme: $('cfg-theme').value,
    dependency_manifest: $('cfg-dependency_manifest').value.trim(),
    use_builtin_runtime: $('cfg-use_builtin_runtime').checked,
    auto_update_dependencies: $('cfg-auto_update_dependencies').checked,
    require_admin: $('cfg-require_admin').checked,
    auto_disable_feed_on_native_dlss: $('cfg-auto-disable-feed') ? $('cfg-auto-disable-feed').checked : true,
    prefer_internal_dependencies: $('cfg-prefer-internal-deps') ? $('cfg-prefer-internal-deps').checked : true,
    download_boost: $('cfg-download_boost') ? $('cfg-download_boost').value : 'auto',
    download_line: $('cfg-download_line') ? $('cfg-download_line').value : 'auto',
  };
  await call('save_config', data);
  // Mod 备份目录单独走 set_mod_backup_dir：它要按新位置校验"别落进 Mod 库/中转目录"，
  // 校验不过后端会保持原值并给出原因（用户 2026-10-02 要求：设置里能自行选择备份目录）。
  let backupNote = '';
  const backupInput = $('cfg-mod_backup_dir');
  if (backupInput) {
    const wanted = backupInput.value.trim();
    const current = (state.config && state.config.mod_backup_dir) || '';
    if ((wanted || 'mod-backup') !== current) {
      const result = await call('set_mod_backup_dir', { value: wanted });
      if (result && result.ok === false) {
        backupNote = `　⚠ ${result.message || 'Mod 备份目录没改'}`;
        backupInput.value = current;
      } else if (result && result.changed) {
        backupNote = `　Mod 备份目录已改为 ${result.dir}（旧目录里的备份原样保留，新目录会在下次扫描后重新整份备份一次）`;
      }
    }
  }
  await refreshFromState();
  $('settings-status').textContent = '设置已保存' + backupNote;
}

async function refreshFromState() {
  const s = await call('get_state');
  state.config = s.config;
  // 未读公告（info/warning）：由 boot() 弹一次，**不锁启动**、看完即走。
  // 异常状态预警（critical）不走这里 —— 见 runOneClickLaunch 里的 prelaunch_alerts。
  state.announcements = s.announcements || [];
  // 关键文件被反复删掉（疑似杀毒软件隔离）：后端算好的提醒。
  // ⚠ 这里**只存数据、不弹窗** —— 弹窗挂在「一键启动」里（用户 2026-10-01 决定：
  //   「改到一键启动」）。理由：缺文件的后果只在你要启动游戏时才会发生，而且紧接着
  //   就会自动补回来，"补了又被删"的现场在一键启动那一刻最清楚；平时打开管理器
  //   只想看 Mod 库时不该被打断（后台仍会采样并在日志里留一行）。
  state.fileWatchdog = s.file_watchdog || null;
  // 公告"跟着数据走"：后端预热线程常在首屏之后才把公告填上来，所以每次刷新都检查一次
  // （maybeShowAnnouncements 幂等：弹过、记过已读的不会再弹）。
  setTimeout(() => { maybeShowAnnouncements(); }, 400);
  await refreshPaths(s.config);
  const injectUi = s.config.inject_reshade_ui !== false;
  if ($('cfg-inject-reshade-ui')) {
    $('cfg-inject-reshade-ui').checked = injectUi;
  }
  if ($('cfg-reshade-panel-font')) {
    $('cfg-reshade-panel-font').checked = s.config.reshade_panel_font !== false;
  }
  // 「整合 Mod 快捷键」滑块 + 面板现状：后端 panel_status 是唯一判据，别在前端另写一套。
  if ($('cfg-unified-hotkeys')) {
    $('cfg-unified-hotkeys').checked = s.config.hotkey_takeover === true;
  }
  const panel = s.hotkey_panel || null;
  if ($('hotkey-panel-status') && panel) {
    if (s.config.hotkey_takeover !== true) {
      $('hotkey-panel-status').textContent = panel.addon_present
        ? `面板已就位（${panel.base_dir}）；当前未接管，Mod 自带按键照常生效。`
        : '';
    } else if (!panel.possible) {
      $('hotkey-panel-status').textContent = `⚠ 面板不可用：${panel.reason}。已保持 Mod 自带按键不被锁死。`;
    } else if (panel.ready) {
      $('hotkey-panel-status').textContent = `面板已注入 ReShade（${panel.base_dir}）。进游戏按 Home 打开。`;
    } else {
      $('hotkey-panel-status').textContent = '⚠ 开关是开的，但面板还没写就位 —— 下次「一键启动」会重试。';
    }
  }
  // Mod 备份仓：库里新见到的 Mod 会自动整份复制进去（纯备份、不压缩；只增不减，程序从不删它）
  const backup = s.mod_backup || null;
  if (backup) {
    const backupOn = backup.enabled !== false;
    // 总开关（用户 2026-10-02：「默认开，关了就不备份」）：开关状态与"目录输入框能否编辑"同步 ——
    // 关着的时候目录/「选择…」置灰，避免"填了目录却没在备份"的困惑。
    if ($('cfg-mod-backup-enabled')) $('cfg-mod-backup-enabled').checked = backupOn;
    if ($('cfg-mod_backup_dir')) $('cfg-mod_backup_dir').disabled = !backupOn;
    if ($('mod-backup-choose')) $('mod-backup-choose').disabled = !backupOn;
    if ($('path-mod-backup')) $('path-mod-backup').textContent = backup.dir || '';
    if ($('mod-backup-status')) {
      const mb = ((backup.bytes || 0) / 1048576).toFixed(1);
      let text;
      if (!backupOn) {
        text = `Mod 备份已关闭 —— 不会再复制任何 Mod；已有 ${backup.count || 0} 个备份（${mb} MB）原样保留，程序不会删`;
      } else {
        text = `已备份 ${backup.count || 0} 个 Mod（${mb} MB）· 只增不减，程序不会删除这里的文件`;
        if (backup.pending) text += ` · 还有 ${backup.pending} 个待打包`;
        if (backup.overlaps_library) text += ' · ⚠ 备份目录与 Mod 库重叠，已暂停备份（请到设置里改「Mod 备份目录」）';
      }
      $('mod-backup-status').textContent = text;
    }
  }
  const dlss5 = s.dlss5_status || {};
  const addonCfg = (s.component_addon_status || {}).config || {};
  if ($('cfg-dlss5-addon')) {
    $('cfg-dlss5-addon').checked = addonCfg.dlss5_addon_enabled !== false;
  }
  if ($('cfg-firstperson-addon')) {
    $('cfg-firstperson-addon').checked = addonCfg.firstperson_addon_enabled !== false;
  }
  const modsOn = s.config.efmi_injection !== false;
  if ($('cfg-efmi-injection')) {
    $('cfg-efmi-injection').checked = modsOn;
  }
  if ($('cfg-third-party-mods')) {
    $('cfg-third-party-mods').checked = modsOn;
  }
  // 「强行关闭角色 Mod 互斥」拨钮：打开后勾选不再自动取消同角色的其它 Mod
  const allowSame = s.config.allow_same_character_mods === true;
  if ($('cfg-allow-same-character')) {
    $('cfg-allow-same-character').checked = allowSame;
  }
  const mutualHint = $('mutual-hint');
  if (mutualHint) {
    mutualHint.textContent = allowSame
      ? '⚠ 同角色互斥已关闭：同角色多个 Mod 可同时勾选（不冲突才这样配）。选择自动保存。把 .zip / .7z / .rar 拖到页面任意处即可导入。'
      : '同角色自动互斥，选择自动保存。把 .zip / .7z / .rar 拖到页面任意处即可导入。';
  }
  const modList = $('mod-list');
  if (modList) modList.classList.toggle('mods-disabled', !modsOn);
  if ($('library-status') && !modsOn) {
    $('library-status').textContent = '第三方服装 Mod 已关闭：EFMI 引擎不注入，这里的勾选暂时都不生效。';
  }
  if ($('dlss5-status')) {
    const lines = [
      `底座 d3d12.dll : ${dlss5.dlss5_dll_exists ? '已就位' : '缺失'}  ${dlss5.dlss5_dll || ''}`,
      `第一人称插件   : ${dlss5.enhancer_addon_exists ? '已就位' : '缺失'}`,
      `EFMI d3d11.dll : ${dlss5.efmi_dll || '(未找到)'}`,
      `XXMI 注入库    : ${dlss5.enabled ? '已开启' : '未开启'}`,
      (dlss5.extra_libraries || '(空)'),
    ];
    $('dlss5-status').textContent = lines.join('\n');
  }
  if (s.config.last_tab) showTab(s.config.last_tab, false);
  const renderApi = s.render_api || 'unknown';
  if ($('render-api-status')) {
    $('render-api-status').textContent = renderApi === 'vulkan'
      ? '上次启动：Vulkan（服装 Mod 不生效，请在启动器里点 DirectX 11 启动）'
      : renderApi === 'd3d12'
        ? '上次启动：DirectX 12（服装 Mod 不生效，请在启动器里点 DirectX 11 启动）'
        : renderApi === 'd3d11'
          ? '上次启动：DirectX 11'
          : '上次启动：未知';
  }
  const sbm = s.secondary_motion_status || {};
  if ($('sbm-status')) {
    const proxies = sbm.proxies || {};
    const lines = [
      `工具版本 : ${sbm.tool_version || '(未配置)'}   ${sbm.manager_exists ? 'exe 就位' : 'exe 缺失'}`,
      `工具目录 : ${sbm.tool_dir || '(未找到)'}`,
      `注入状态 : ${sbm.injected ? '两个 proxy 已就位' : '未注入'}`,
      `插件本体 : ${sbm.plugin_exists ? 'plugin\\sbm.dll 已就位' : 'plugin\\sbm.dll 缺失'}`,
    ];
    for (const [name, info] of Object.entries(proxies)) {
      lines.push(`  ${name}: ${info.installed ? 'proxy ' + info.size + ' B' : '未注入'} / 原版备份 ${info.backup ? '有' : '无'}`);
    }
    if (sbm.runtime && sbm.runtime.state) {
      lines.push(`运行时   : ${sbm.runtime.state} mode=${sbm.runtime.mode || '-'} (${Math.round(sbm.runtime.age_s || 0)} 秒前)`);
    }
    $('sbm-status').textContent = lines.join('\n');
  }
  if ($('cfg-secondary_motion_injection')) {
    $('cfg-secondary_motion_injection').checked = s.config.secondary_motion_injection === true;
  }
  if ($('cfg-poser_injection')) {
    $('cfg-poser_injection').checked = s.config.poser_injection !== false;
  }
  // Endfield Poser：状态汇总到设置页的状态窗（启动页只留滑块与按钮，遵循"启动页少放文字窗"的约定）
  const poserStatus = s.poser_status || {};
  if ($('poser-status')) {
    const pv = poserStatus.proxies || {};
    const plines = [
      `安装包   : ${poserStatus.pack_ready ? (poserStatus.pack_version || '(版本未知)') : '未下载'}   ${poserStatus.pack_dir || ''}`,
      `游戏内   : ${poserStatus.installed ? 'plugin\\poser.dll 已就位' : (poserStatus.parked ? '已按开关停用（可逆）' : '未安装')}`,
      `loader   : ${poserStatus.loader_kind ? poserStatus.loader_kind + ' 版 proxy' : '不在位'}${poserStatus.proxy_owned ? '（安装记录归 Poser）' : ''}`,
      `表情校准 : ${poserStatus.face_count || 0} 份    姿态库: ${poserStatus.pose_count || 0} 条`,
    ];
    for (const [pname, pinfo] of Object.entries(pv)) {
      plines.push(`  ${pname}: ${pinfo.exists ? (pinfo.kind || '?') + ' proxy ' + pinfo.size + ' B' : '不在'} / 系统原版备份 ${pinfo.backup ? '有' : '无'}`);
    }
    if ((poserStatus.other_plugins || []).length) plines.push(`共存插件 : ${poserStatus.other_plugins.join(', ')}`);
    if (poserStatus.record_consistent === false) plines.push('⚠ 安装记录与实际文件不一致（可能是手动更新过它）');
    const pweb = poserStatus.web || {};
    plines.push(`摆姿页   : ${pweb.reachable ? '已连接 127.0.0.1:18923' : (pweb.reason || '未连接')}`);
    const ptail = poserStatus.log_tail || [];
    if (ptail.length) plines.push('--- plugin\\poser_log.txt 末尾 ---', ...ptail.slice(-4));
    $('poser-status').textContent = plines.join('\n');
  }
  if (!s.config.xxmi_launcher && s.detected_xxmi) {
    state.config.xxmi_launcher = s.detected_xxmi;
    $('cfg-xxmi_launcher').value = s.detected_xxmi;
    await call('save_config', { xxmi_launcher: s.detected_xxmi });
  }
  if (!s.config.migoto_loader && s.detected_migoto_loader) {
    state.config.migoto_loader = s.detected_migoto_loader;
    $('cfg-migoto_loader').value = s.detected_migoto_loader;
    await call('save_config', { migoto_loader: s.detected_migoto_loader });
  }
  if (!s.config.official_launcher && s.detected_official_launcher) {
    state.config.official_launcher = s.detected_official_launcher;
    $('cfg-official_launcher').value = s.detected_official_launcher;
    await call('save_config', { official_launcher: s.detected_official_launcher });
  }
  // 后端还在后台预热（全盘探测）时 detected_* 是空的：稍后再静默刷新一次补上，
  // 这样"加载页尽早出现"和"探测结果照旧可用"两件事都成立（2026-10-01 改）。
  if (s.warming && !state.__warmingRetry) {
    state.__warmingRetry = true;
    setTimeout(() => {
      state.__warmingRetry = false;
      refreshFromState().catch(() => {});
    }, 1500);
  }
  state.mods = s.mods || [];
  const validIds = new Set(state.mods.map(m => m.id));
  state.selected = new Set((s.config.selected_mods || []).filter(id => validIds.has(id)));
  sanitizeSelection();
  state.dependency_report = s.dependency_report || {};
  renderMods();
  renderDependencies();
}

async function startFullUpdate(dryRun, statusEl) {
  const out = statusEl || $('dep-results');
  out.textContent = dryRun ? '检查中...' : '自动安装/更新中...';
  $('dep-progress').value = 0;
  $('dep-progress').max = 100;
  $('dep-progress-text').textContent = dryRun ? '检查中...' : '自动安装/更新中...';
  await call('start_full_update', dryRun);
  await pollDependencyProgress(out);
}

// 依赖任务里"已完成的组件数"，用来做「每装完一个就刷新一次列表」的增量刷新
let lastDoneCount = 0;

async function pollDependencyProgress(statusEl) {
  const out = statusEl || $('dep-results');
  const isDepPanel = out === $('dep-results');
  while (true) {
    const progress = await call('get_dependency_progress');
    const total = progress.total || 0;
    const current = progress.current || 0;
    const percent = Number(progress.percent || 0);
    // **"下载完成"弹出来之前不要到 100%**（用户 2026-10-01 要求）：任务还在跑时封顶 99%，
    // 只有 running=False（真正结束）才允许显示 100%。否则 99.9% 会被 toFixed(0) 显示成 100%，
    // 看起来像"已经好了却没弹完成"。
    const stillRunning = progress.running !== false;
    const shownPercent = stillRunning ? Math.min(99, percent) : Math.min(100, percent);
    $('dep-progress').max = 100;
    $('dep-progress').value = Math.max(0, shownPercent);
    // 进度条旁**只显示总进度**（百分比 + 已完成项数）；带字节的细节交给下面的日志框，
    // 否则这里会变成「0/3 XX: 12.3/27.9 MB」——两个不同量纲的进度挤在一起，看着像对不上。
    // 分母现在是**全部下载项**（随包资产 + XXMI/Libs/EFMI + DLSS5 在线组件 + 依赖清单 + 乳摇），
    // 不再只是"3 个组件"（2026-10-01 用户要求「进度条要全都管」）。
    $('dep-progress-text').textContent = total
      ? `${shownPercent.toFixed(0)}%  ·  已完成 ${current}/${total} 项`
      : (progress.message || '');

    if (current < lastDoneCount) lastDoneCount = 0;   // 进程号回退 = 新任务，重新计数
    // 每装完一个组件就刷新一次依赖列表（用户要求），别等全部完成才刷新。
    if (progress.running && current > lastDoneCount) {
      lastDoneCount = current;
      try {
        await refreshFromState();
      } catch (err) {
        /* 单个组件刷新失败不影响整体任务 */
      }
    }
    // 详细过程（含"尝试线路 / 直连失败 / 断点续传 / 校验"等）全部写进下面那个日志框，
    // 它专门用来展示下载细节，所以这里不做过滤；界面上方只留进度条与一行状态。
    const logBox = $('dep-log');
    if (logBox && (progress.log || []).length) {
      logBox.textContent = progress.log.join('\n');
      logBox.scrollTop = logBox.scrollHeight;
    }
    if (!isDepPanel) {
      // 在别处触发时（设置页的一键安装/更新），把实时进度写到那块面板里。
      // 「尝试线路：X」「线路 X 失败：…」这些是**自动换线路的中间过程**，不是下载失败 ——
      // 直接铺在界面上会让人以为出错了（用户就因此反馈过"怎么下载又失败了"），所以滤掉。
      const innerLogs = (progress.log || []).filter(line => !isNoisyLine(line));
      out.textContent = `${percent.toFixed(0)}%  ${current}/${total}\n${progress.message || ''}`
        + (innerLogs.length ? '\n\n' + innerLogs.slice(-12).join('\n') : '');
    }
    if (!progress.running) {
      const done = progress.results || [];
      const failedCount = done.filter(r => /失败/.test(String((r || {}).status || ''))).length;
      // 「已下载」既不是失败也不是完成：要问用户何时安装（用户 2026-10-01 要求
      // 「下载完应该跳一个弹窗，让用户选择是立即重启程序更新还是稍后」）。
      const downloaded = done.find(r => /已下载/.test(String((r || {}).status || '')));
      const doneMessage = done.length === 0
        ? '任务结束'
        : (failedCount ? `完成，但有 ${failedCount} 项失败`
          : (downloaded ? String(downloaded.message || '更新已下载完成')
            : `下载与安装完成（${done.length} 项）✅`));
      // ⚠️ **不要把结果明细以原始 JSON 倒出来**（用户 2026-09-29 原话：「下载界面下面
      // 不需要这一堆」——那串 `[{key,status,message,version,path}, …]` 全是他看不懂的
      // 内部字段）。成功的项没有信息量，所以只列"非成功"的那几项，一行一项说人话。
      const okStatus = /已安装|已是最新|已就位|已展开|已更新|已补齐|installed|up_to_date|present|extracted/i;
      const problems = done.filter(r => !okStatus.test(String((r || {}).status || '')));
      out.textContent = doneMessage
        + (problems.length
          ? '\n\n' + problems.map((r) => {
            const key = String((r || {}).key || '');
            const status = String((r || {}).status || '');
            const message = String((r || {}).message || '').trim();
            return `· ${key}：${status}${message && message !== status ? `（${message}）` : ''}`;
          }).join('\n')
          : '');
      if (logBox) {
        logBox.textContent = `${logBox.textContent}\n—— ${doneMessage} ——`;
        logBox.scrollTop = logBox.scrollHeight;
      }
      showToast(doneMessage);
      setStatus(doneMessage);
      try {
        await refreshFromState();
      } catch (err) {
        /* 刷新失败不影响任务结果展示 */
      }
      if (downloaded) {
        await askApplyUpdate(downloaded.message);
      }
      break;
    }
    await new Promise(resolve => setTimeout(resolve, 400));
  }
}

// ── 新手引导（分步 tour）──────────────────────────────────────────────────────
// 用户 2026-10-01 要求：不要上来就推"一键启动"，先问要不要引导；引导顺序是
// 依赖页（箭头指「自动安装/更新」并建议点）→ 能拖 zip → 一键启动 → 设置页能一键还原。
const TOUR_STEPS = [
  {
    tab: 'dependencies',
    target: 'dep-update-all-btn',
    title: '第一步：先把组件装齐',
    body: '这里是「依赖」页。点这个「自动安装/更新」按钮，程序会自动下载并安装\n'
      + 'XXMI Launcher、XXMI 库、EFMI、DLSS5 组件等全部依赖（需要联网）。\n\n'
      + '建议先点它，等装完再去启动。',
  },
  {
    tab: 'library',
    target: '',
    title: '第二步：把 Mod 拖进来',
    body: '在「Mod 库」页，把 Mod 的压缩包（.zip / .7z / .rar）直接拖到页面任意位置即可导入：\n'
      + '松手后自动解压进库，并尝试识别角色归属。\n\n'
      + '同一个角色只保留一个 Mod（自动互斥），避免游戏崩溃。',
  },
  {
    tab: 'launch',
    target: 'oneclick-launch-btn',
    title: '第三步：一键启动',
    body: '点这个「一键启动」：程序会补齐缺失组件、同步注入库、跑一遍初始化自检，\n'
      + '然后拉起 XXMI Launcher（不会自动进游戏，进游戏在 XXMI 里点 Start）。\n\n'
      + '第一次可能会提示"已临时拉起 XXMI 生成配置文件"，看到后再点一次即可。',
  },
  {
    tab: 'settings',
    target: 'game-restore-btn',
    title: '第四步：随时可以还原',
    body: '「设置」页有「一键还原游戏本体」：\n'
      + '本程序对游戏目录做的任何改动都可回滚（净化前会完整备份、只移动不删除）。\n\n'
      + '出问题就点它，游戏目录会回到原版状态。',
  },
];

let tourIndex = 0;
let tourActive = false;

function tourShow(stepIndex) {
  const step = TOUR_STEPS[stepIndex];
  if (!step) return;
  const wrap = $('tour');
  const spot = $('tour-spot');
  const card = $('tour-card');
  if (!wrap || !spot || !card) return;
  tourIndex = stepIndex;
  tourActive = true;
  wrap.classList.remove('hidden');
  $('tour-progress').textContent = `${stepIndex + 1} / ${TOUR_STEPS.length}`;
  $('tour-title').textContent = step.title;
  $('tour-body').textContent = step.body;
  $('tour-prev').style.visibility = stepIndex === 0 ? 'hidden' : 'visible';
  $('tour-next').textContent = stepIndex === TOUR_STEPS.length - 1 ? '开始使用' : '下一步';
  if (step.tab) showTab(step.tab);
  // 等两帧再量位置：切换页面后布局才稳定
  requestAnimationFrame(() => {
    const el = step.target ? $(step.target) : null;
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' });
    requestAnimationFrame(() => {
      if (el) {
        const r = el.getBoundingClientRect();
        const pad = 8;
        Object.assign(spot.style, {
          left: `${r.left - pad}px`, top: `${r.top - pad}px`,
          width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px`,
        });
        const below = r.bottom + 16;
        const cardTop = (below + 230 < window.innerHeight) ? below : Math.max(16, r.top - 250);
        Object.assign(card.style, {
          left: `${Math.min(Math.max(16, r.left), Math.max(16, window.innerWidth - 440))}px`,
          top: `${cardTop}px`, transform: 'none',
        });
      } else {
        // 没有具体目标（例如"能拖 zip"这一步）：聚光收成一个点，卡片居中
        Object.assign(spot.style, { left: '50%', top: '40%', width: '0px', height: '0px' });
        Object.assign(card.style, { left: '50%', top: '46%', transform: 'translate(-50%, 0)' });
      }
    });
  });
}

function tourFinish() {
  tourActive = false;
  const wrap = $('tour');
  if (wrap) wrap.classList.add('hidden');
  // 跳过与走完都记下来，下次启动不再问
  try {
    const p = call('save_config', { onboarding_done: true });
    if (p && p.catch) p.catch(() => {});
  } catch (err) { /* 忽略 */ }
}

function initTour() {
  const wrap = $('tour');
  if (!wrap) return;
  $('tour-skip').onclick = () => tourFinish();
  $('tour-next').onclick = () => {
    if (tourIndex >= TOUR_STEPS.length - 1) tourFinish();
    else tourShow(tourIndex + 1);
  };
  $('tour-prev').onclick = () => { if (tourIndex > 0) tourShow(tourIndex - 1); };
  window.addEventListener('resize', () => { if (tourActive) tourShow(tourIndex); });
}

// 下载完成后问用户：立即重启安装，还是稍后（用户 2026-10-01 要求）
async function askApplyUpdate(message) {
  // 用户要求：「下载完应该跳一个弹窗，让用户选择是立即重启程序更新还是稍后」。
  // 用带自定义按钮文字的模态框（而不是"确定/取消"），这样和上一个"是否下载"的
  // 确认不会混在一起 —— 2026-10-01 用户反馈"只有动态气泡、没有选择弹窗"，
  // 就是因为两个确认框按钮长得一样、被连着点掉了。
  const yes = await showModalDialog({
    title: '更新已下载',
    message: `${message || '更新已下载完成'}\n\n`
      + '· 立即重启安装：程序会自动退出、替换文件并重启为新版\n'
      + '· 稍后：保留已下载的更新包，下次启动时再问你',
    okText: '立即重启安装',
    cancelText: '稍后',
  });
  if (!yes) {
    setStatus('更新已下载完成，下次启动时会再问你一次');
    return;
  }
  setStatus('正在准备安装，程序即将退出并重启…');
  try {
    const r = await call('apply_app_update');
    if (!r || !r.ok) await showAlert((r && r.message) || '安装失败', '更新');
  } catch (err) {
    await showAlert(`安装失败：${err.message || err}`, '更新');
  }
}

let logTimer = null;

async function refreshLog() {
  // 日志窗每秒轮询一次，而 call() 失败会弹模态框 —— 后端忙 / 自更新重启期间
  // 会以 1 秒 1 个的速率往屏幕上叠弹窗，点掉一个又冒一个（2026-10-01 修）。
  let result;
  try {
    result = await call('read_launch_log', 500);
  } catch (err) {
    setStatus('读取日志失败：' + ((err && err.message) ? err.message : err));
    return;
  }
  $('log-text').textContent = result.text || '(日志为空)';
  $('log-text').scrollTop = $('log-text').scrollHeight;
}

function openLog() {
  $('log-modal').classList.remove('hidden');
  refreshLog();
  if (logTimer) clearInterval(logTimer);
  logTimer = setInterval(refreshLog, 1000);
}

function closeLog() {
  $('log-modal').classList.add('hidden');
  if (logTimer) {
    clearInterval(logTimer);
    logTimer = null;
  }
}

async function clearLog() {
  await call('clear_launch_log');
  await refreshLog();
}

async function forceCloseGame() {
  if (!await showConfirm('将强制结束 Endfield.exe / migoto_loader2.exe / loader.exe 残留进程。\n\n如果只是窗口关闭后进程没退出，可以继续。是否继续？')) return;
  setStatus('正在强制结束残留进程...');
  const result = await call('force_close_game');
  setStatus(result.ok ? `已结束: ${(result.killed || []).join(', ') || '无运行进程'}` : `结束失败: ${(result.errors || []).join('; ')}`);
}

async function exportDiagnostics() {
  setStatus('正在导出诊断包...');
  const result = await call('export_diagnostics');
  if (result && result.ok) {
    if (!$('log-modal').classList.contains('hidden')) {
      const box = $('log-text');
      box.textContent += `

[诊断包] ${result.path}
`;
      box.scrollTop = box.scrollHeight;
    }
    setStatus(`诊断包已导出: ${result.path}`);
    // 用户 2026-10-01 要求：导出诊断包后弹窗给出 GitHub 与 QQ 群的反馈方式，并要求附上现象
    showFeedbackModal(result.path || '');
  } else {
    setStatus(`导出诊断包失败: ${result.message || '未知错误'}`);
    await showAlert(`导出诊断包失败：${result && result.message ? result.message : '未知错误'}`, '导出诊断包');
  }
}

// ── 诊断包导出后的「怎么反馈」弹窗（GitHub issue / QQ 群 + 附上现象） ──────────
function showFeedbackModal(zipPath) {
  const modal = $('feedback-modal');
  if (!modal) return;
  $('feedback-zip').textContent = zipPath || '(看下面的日志窗里的路径)';
  if ($('feedback-qq')) $('feedback-qq').textContent = FEEDBACK_QQ;
  if ($('feedback-qq-answer')) $('feedback-qq-answer').textContent = FEEDBACK_QQ_ANSWER;
  const issueUrl = (window.__mcLinks && window.__mcLinks.issues) || '';
  if ($('feedback-issue-link')) {
    // 网址直接点开（全局委托负责调用 open_external，见 boot 里的说明）
    $('feedback-issue-link').href = issueUrl || '#';
    $('feedback-issue-link').textContent = issueUrl || '（见「说明」页的反馈地址）';
  }
  if ($('feedback-open-zip')) {
    const target = zipPath || '';
    $('feedback-open-zip').onclick = () => {
      if (target) call('open_path_in_explorer', target).catch(() => {});
    };
  }
  if ($('feedback-copy-zip')) {
    $('feedback-copy-zip').onclick = async () => {
      try { await navigator.clipboard.writeText(zipPath || ''); setStatus('诊断包路径已复制'); }
      catch (err) { setStatus(`复制失败，请手动复制: ${zipPath || ''}`); }
    };
  }
  if ($('feedback-copy-qq')) {
    $('feedback-copy-qq').onclick = async () => {
      try { await navigator.clipboard.writeText(`${FEEDBACK_QQ}（验证答案：${FEEDBACK_QQ_ANSWER}）`); setStatus('QQ 群号已复制'); }
      catch (err) { setStatus(`复制失败，请手动复制: ${FEEDBACK_QQ}`); }
    };
  }
  if ($('feedback-modal-close')) $('feedback-modal-close').onclick = () => modal.classList.add('hidden');
  modal.classList.remove('hidden');
}

async function previewLaunch() {
  const result = await call('launch_preview');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
}

async function launch() {
  if (!state.config.xxmi_launcher) {
    await showAlert(`还没有配置 XXMI Launcher 路径。
请到“设置”页选择 XXMI Launcher.exe，或点击“自动检测 XXMI”。`);
    showTab('settings');
    return;
  }
  if (!await showConfirm('确定要完成准备并打开 XXMI Launcher 吗？（不会自动启动游戏；请在 XXMI 里点 Start）')) return;
  openLog();
  setStatus('准备并启动中...');
  const result = await call('launch');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  setStatus('已发送启动命令');
}

async function launchGame() {
  if (!state.config.xxmi_launcher) {
    await showAlert(`还没有配置 XXMI Launcher 路径。
请到“设置”页选择 XXMI Launcher.exe，或点击“自动检测 XXMI”。`);
    showTab('settings');
    return;
  }
  if (!await showConfirm('确定要完成准备并通过 XXMI/EFMI 启动游戏吗？\nXXMI 会自动加上 -force-d3d11。')) return;
  openLog();
  setStatus('准备并通过 XXMI 启动游戏...');
  const result = await call('launch_game');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  setStatus('已通过 XXMI 发送启动请求');
}

async function enableSafeMode() {
  if (!await showConfirm('反作弊兼容模式会：移除 EndfieldModController 写入游戏目录的 3 个集成文件，把 dxgi.dll / d3d12.dll 重命名为 *.endfieldmodcontroller.disabled，并改用 XXMI extra_libraries 注入 ReShade。\n\n这是可回滚操作，是否继续？')) return;
  openLog();
  setStatus('正在切换反作弊兼容模式...');
  const result = await call('enable_anti_cheat_safe_mode');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  await refreshFromState();
  setStatus(result.ok ? '反作弊兼容模式已启用' : '已切换，但有警告，请查看日志');
}

async function restoreSafeMode() {
  if (!await showConfirm('是否恢复游戏目录 ReShade：把 *.endfieldmodcontroller.disabled 改回 dxgi.dll / d3d12.dll，并恢复 XXMI extra_libraries 备份？')) return;
  setStatus('正在恢复游戏目录 ReShade...');
  const result = await call('restore_anti_cheat_safe_mode');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  await refreshFromState();
  setStatus(result.ok ? '已恢复游戏目录 ReShade' : '恢复时出现警告，请查看日志');
}

async function enableD3D12Mode() {
  if (!await showConfirm('dxgi改名d3d12模式会把游戏目录的 dxgi.dll 重命名为 *.endfieldmodcontroller.disabled，保留 d3d12.dll 作为 ReShade 代理，并把 EndfieldModController 集成文件写回游戏目录。是否继续？')) return;
  openLog();
  setStatus('正在切换 dxgi→d3d12 模式...');
  const result = await call('enable_d3d12_proxy_mode');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  await refreshFromState();
  setStatus(result.ok ? 'dxgi→d3d12 模式已启用' : '已切换，但有警告，请查看日志');
}

async function restoreD3D12Mode() {
  if (!await showConfirm('恢复 dxgi 代理：把 dxgi.dll.endfieldmodcontroller.disabled 改回 dxgi.dll，并移除 EndfieldModController 集成文件？')) return;
  setStatus('正在恢复 dxgi 代理...');
  const result = await call('restore_d3d12_proxy_mode');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  await refreshFromState();
  setStatus(result.ok ? '已恢复 dxgi 代理' : '恢复时出现警告，请查看日志');
}

async function launchMigotoLoader() {
  // Official XXMI Launcher GUI mode.  Do not use the custom 3DMigoto loader,
  // do not auto-start the game, and do not write proxy DLLs into the game dir.
  // 留空**不再直接拦下**：后端会自动回落到内置 XXMI（没有就下载）。
  // 只有当内置那份也没装、且用户也没填路径时，后端才会抛错 —— 下面统一兜住并讲清去哪装。
  if (!state.config.xxmi_launcher) {
    logLine('未填 XXMI 路径 —— 将使用内置那份（没有会自动下载安装）');
  }
  if (!await showConfirm('打开官方 XXMI Launcher（EFMI 图形界面）？\n不会自动启动游戏，也不会使用自定义 Loader。')) return;
  openLog();
  setStatus('正在打开官方 XXMI Launcher...');
  let result;
  try {
    result = await call('launch_official_gui');
  } catch (err) {
    const reason = err && err.message ? err.message : String(err);
    logLine(`✗ 打开 XXMI 失败：${reason}`);
    setStatus('打开 XXMI 失败：' + reason);
    await showAlert(
      `打开 XXMI 失败：\n${reason}\n\n到「依赖」页点「自动安装/更新」装好内置 XXMI，`
      + '或在设置页填上你自己的 XXMI Launcher 路径后重试。',
      '打开失败'
    );
    return;
  }
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  setStatus('官方 XXMI Launcher 已打开；请在 EFMI 界面里启动游戏');
}

async function openPath(kind) {
  const info = await call('log');
  const map = { controller: info.controller, reshade: info.reshade, staging: info.staging };
  await call('open_path', map[kind]);
}

async function checkAndRepairIntegrity() {
  setStatus('检查完整性...');
  const report = await call('check_integrity');
  if (report.ok) {
    $('launch-status').textContent = JSON.stringify(report, null, 2);
    setStatus('完整性检查通过');
    return;
  }
  const missing = (report.failures || []).map(item => item.message).join('\n');
  if (!await showConfirm(`发现缺失文件：
${missing}

是否自动修复？`)) return;
  setStatus('修复中...');
  // 修复会真的去装组件 / 补随包资产（可能几百 MB），**必须让用户看到进度** ——
  // 直接打开日志弹窗（它 1 秒轮询一次后端日志，"repair: ..." 每一步都会实时出现）。
  // 2026-10-01：以前这里只写一句"修复中"，大下载时会让人以为界面卡死了。
  if ($('log-modal').classList.contains('hidden')) openLog();
  const result = await call('repair_integrity');
  $('launch-status').textContent = JSON.stringify(result, null, 2);
  const ok = result.integrity && result.integrity.ok;
  setStatus(ok ? '修复完成' : '修复后仍有缺失');
  if (!ok) openLog();
}

async function auditGameInjections(silent = false) {
  if (!silent) setStatus('正在检查游戏目录注入...');
  const result = await call('audit_game_injections');
  const box = $('game-inject-status');
  if (box) box.textContent = JSON.stringify(result, null, 2);
  if (!silent) setStatus(result.ok ? '游戏目录干净，没有第三方注入 DLL' : `发现 ${(result.suspicious || []).length} 个第三方注入文件`);
  return result;
}

async function cleanGameInjections() {
  const audit = await auditGameInjections(true);
  if (audit.ok) {
    setStatus('游戏目录本来就干净');
    return;
  }
  const names = (audit.suspicious || [])
    .map(item => `${item.kind === 'plugin_payload' ? '插件' : '代理 DLL'} ${item.name}`)
    .join(String.fromCharCode(10));
  const message = ['发现以下第三方注入文件：', names, '',
    '将把它们改名停放（有 .bak 的会恢复原版系统 DLL），并注入的游戏插件一并停用。',
    '这是可撤销操作，是否继续？'].join(String.fromCharCode(10));
  if (!await showConfirm(message)) return;
  openLog();
  setStatus('正在清理游戏目录注入...');
  const result = await call('clean_game_injections');
  $('game-inject-status').textContent = JSON.stringify(result, null, 2);
  await auditGameInjections(true);
  setStatus(result.ok ? '已清理游戏目录注入，请重新启动游戏测试' : '清理完成但有警告，请查看日志');
}

async function restoreGameInjections() {
  if (!await showConfirm('撤销上一次的注入清理，把停放的文件改回去？')) return;
  const result = await call('restore_game_injections');
  $('game-inject-status').textContent = JSON.stringify(result, null, 2);
  setStatus(result.ok ? '已撤销注入清理' : (result.message || '撤销失败'));
}

function bind() {
  document.querySelectorAll('.tab').forEach(tab => tab.onclick = () => showTab(tab.dataset.tab));
  $('scan-btn').onclick = scan;
  // 辅助 Mod 页的两个按钮（用户 2026-10-01 方案④）
  if ($('assist-scan-btn')) $('assist-scan-btn').onclick = scan;
  if ($('assist-open-lib-btn')) {
    $('assist-open-lib-btn').onclick = () => call(
      'open_path_in_explorer', (state.config && state.config.library_dir) || '');
  }
  $('prepare-btn').onclick = prepare;
  $('dep-scan-btn').onclick = async () => { await refreshFromState(); setStatus('依赖状态已刷新'); };
  $('dep-check-btn').onclick = () => startFullUpdate(true);
  $('dep-update-all-btn').onclick = () => startFullUpdate(false);
  $('prepare-launch-btn').onclick = prepare;
  $('open-log-btn').onclick = openLog;
  $('export-diagnostics-btn').onclick = exportDiagnostics;
  if ($('settings-export-diagnostics-btn')) $('settings-export-diagnostics-btn').onclick = exportDiagnostics;
  $('force-close-game-btn').onclick = forceCloseGame;
  $('game-inject-audit-btn').onclick = () => auditGameInjections();
  $('game-inject-clean-btn').onclick = cleanGameInjections;
  $('game-inject-restore-btn').onclick = restoreGameInjections;
  $('log-export-btn').onclick = exportDiagnostics;
  $('integrity-btn').onclick = checkAndRepairIntegrity;
  $('migoto-launch-btn').onclick = launchMigotoLoader;
  $('log-close-btn').onclick = closeLog;
  $('log-refresh-btn').onclick = refreshLog;
  $('log-clear-btn').onclick = clearLog;
  $('save-config-btn').onclick = saveConfig;
  const injectToggle = $('cfg-inject-reshade-ui');
  if (injectToggle) {
    injectToggle.onchange = async () => {
      const enabled = injectToggle.checked;
      state.config.inject_reshade_ui = enabled;
      await call('save_config', { inject_reshade_ui: enabled });
      setStatus(enabled ? 'ReShade 控制面板已开启' : 'ReShade 控制面板已关闭');
    };
  }
  if ($('cfg-reshade-panel-font')) {
    $('cfg-reshade-panel-font').onchange = async () => {
      const enabled = $('cfg-reshade-panel-font').checked;
      state.config.reshade_panel_font = enabled;
      await call('save_config', { reshade_panel_font: enabled });
      setStatus(enabled ? '面板会使用系统中文字体' : '面板不再自动改 ReShade 字体');
    };
  }

  if ($('mod-backup-open')) {
    $('mod-backup-open').onclick = async () => {
      try {
        const result = await call('open_mod_backup_dir');
        if (result && result.ok === false && result.message) setStatus(result.message);
        else setStatus('已打开 Mod 备份文件夹');
      } catch (err) {
        setStatus('打开备份文件夹失败：' + (err && err.message ? err.message : err));
      }
    };
  }

  // 「Mod 备份」总开关（用户 2026-10-02：「默认开，关了就不备份」）——
  // 关掉只停"以后还备不备份"：已有备份一个都不删（只增不减是这条功能的红线）。
  if ($('cfg-mod-backup-enabled')) {
    $('cfg-mod-backup-enabled').onchange = async (event) => {
      const wanted = !!event.target.checked;
      try {
        const result = await call('set_mod_backup_enabled', { enabled: wanted });
        if (!result || result.ok === false) {
          event.target.checked = !wanted;      // 后端没接受就把界面弹回去，别显示假的成功
          setStatus((result && result.message) || '切换 Mod 备份失败');
          return;
        }
        await refreshFromState();
        setStatus(wanted
          ? `Mod 备份已开启：库里新见到的 Mod 会整份复制到 ${result.dir || '备份仓'}`
          : 'Mod 备份已关闭：不再复制任何 Mod（已有备份一个都不删）');
      } catch (err) {
        event.target.checked = !wanted;
        setStatus('切换 Mod 备份失败：' + (err && err.message ? err.message : err));
      }
    };
  }

  // 「选择…」：弹系统文件夹选择框挑 Mod 备份目录，挑完立刻生效（用户 2026-10-02 要求）
  if ($('mod-backup-choose')) {
    $('mod-backup-choose').onclick = async () => {
      try {
        const result = await call('choose_mod_backup_dir');
        if (!result || result.ok === false) {
          setStatus((result && result.cancelled) ? '已取消选择' : ((result && result.message) || '选择备份目录失败'));
          return;
        }
        if ($('cfg-mod_backup_dir')) $('cfg-mod_backup_dir').value = result.configured || '';
        if ($('path-mod-backup')) $('path-mod-backup').textContent = result.dir || '';
        await refreshFromState();
        setStatus(result.changed
          ? `Mod 备份目录已改为 ${result.dir}（旧目录备份保留）`
          : `Mod 备份目录未变：${result.dir}`);
      } catch (err) {
        setStatus('选择备份目录失败：' + (err && err.message ? err.message : err));
      }
    };
  }

  // ── 「整合 Mod 快捷键」：一个开关同时做两件事（锁 Mod 按键 + 注入 ReShade 面板）──
  // 后端 set_hotkey_takeover 会把面板铺好并回报"实际能不能用"；不能用时如实提示，
  // 而且启动链路不会锁键 —— 不允许出现"键锁死了、面板却不存在"（2026-10-01 事故）。
  if ($('cfg-unified-hotkeys')) {
    $('cfg-unified-hotkeys').onchange = async () => {
      const toggle = $('cfg-unified-hotkeys');
      const enabled = toggle.checked;
      toggle.disabled = true;
      try {
        const result = await call('set_hotkey_takeover', enabled);
        state.config.hotkey_takeover = enabled;
        setStatus(result.message || (enabled ? '整合 Mod 快捷键已打开' : '整合 Mod 快捷键已关闭'));
        if ($('hotkey-panel-status')) {
          $('hotkey-panel-status').textContent = !enabled
            ? ''
            : (result.possible
              ? `面板已就位（${(result.panel || {}).base_dir || ''}）。进游戏按 Home 打开。`
              : `⚠ 面板不可用：${result.reason}。已保持 Mod 自带按键不被锁死。`);
        }
        if (enabled && result.possible && !result.game_running) {
          // 重新生成控制器会重写 staging，刷新一下库/状态，避免界面显示旧状态
          await refreshFromState().catch(() => {});
        }
      } catch (err) {
        toggle.checked = !enabled;
        setStatus('切换失败：' + (err && err.message ? err.message : err));
      } finally {
        toggle.disabled = false;
      }
    };
  }

  // 日志窗的 detectLogLevel / logLine / paintLog 定义在文件顶部（顶层），
  // 这里不再重复定义 —— 重复会在 bind() 作用域内遮蔽顶层版本，
  // 而 boot() 调用的是顶层那份，导致 "xxx is not defined"。

  // ── 一键启动：先跑初始化自检（缺什么补什么），再拉起 XXMI ──
  if ($('oneclick-launch-btn')) {
    // 一次完整的「一键启动」：初始化自检（缺什么补什么）→ 拉起 XXMI。
    // 返回 needsSecondStart：**第一次启动**时为 true（本次真的临时拉起过 XXMI 生成
    // 配置文件，或程序尚未初始化），UI 据此在**拉起 XXMI 之后**提示用户再启动一次
    // —— 用户 2026-10-01：「我说的第一次启动是在拉起 xxmi 之后再谈，选项应该是
    //    再次启动和先不启动」。
    // 等 XXMI 退出：XXMI 在把终末地拉起来之后会**自己关闭**，那一刻"游戏起没起来"
    // 才看得出来。用户要求提示改到这个时机（原话：「之前说 xxmi 拉起的时候出的那个弹窗
    // 改成 xxmi 关闭后出，xxmi 会在拉起终末地后自动关闭」）。
    // 最多等 10 分钟；查询失败就当它还在运行，继续等（不打扰用户）。
    const waitXxmiClosed = async (timeoutMs = 10 * 60 * 1000) => {
      const deadline = Date.now() + timeoutMs;
      while (Date.now() < deadline) {
        await new Promise((resolve) => { setTimeout(resolve, 2000); });
        try {
          const state = await call('xxmi_running');
          if (!state || !state.running) return true;
        } catch (err) { /* 查询失败不拦路，继续等 */ }
      }
      return false;
    };

    // XXMI 退出之后，看终末地到底起没起来 —— 这才是"这一把成不成"的判据。
    // 用户要求：「可以在 xxmi 退出后检测终末地状态，如果在拉起后 10s 内退出就弹弹窗」。
    //   ① 等 Endfield.exe 出现（最多 30 秒，XXMI 退出到游戏进程出现之间有个空档）；
    //   ② 出现之后再盯 10 秒 —— 如果它在这 10 秒内就退出了，说明是"启动失败"那种闪退；
    //   ③ 没出现 / 10 秒内退出 ⇒ ok=false，前端据此弹「再启动一次」。
    const watchGameAfterXxmi = async (appearMs = 30000, aliveMs = 10000) => {
      const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
      const appearDeadline = Date.now() + appearMs;
      let sawGame = false;
      while (Date.now() < appearDeadline) {
        await sleep(1000);
        try {
          const g = await call('game_running');
          if (g && g.running) { sawGame = true; break; }
        } catch (err) { /* 查询失败继续等 */ }
      }
      if (!sawGame) return { ok: false, reason: '等了 30 秒没看到终末地进程 —— 游戏没有启动' };
      const aliveDeadline = Date.now() + aliveMs;
      while (Date.now() < aliveDeadline) {
        await sleep(1000);
        try {
          const g = await call('game_running');
          if (!g || !g.running) return { ok: false, reason: '终末地启动后 10 秒内就退出了（启动失败）' };
        } catch (err) { /* 查询失败当作还在跑 */ }
      }
      return { ok: true, reason: '' };
    };

    const runOneClickLaunch = async () => {
      logLine('开始一键启动…');
      // ①-0 异常状态预警（内容来自仓库里的 alerts.json，作者随时改、不用发版）
      //   用户 2026-09-30 要求：「在按一键启动的时候如果是异常状态要**每次都弹**弹窗展示情况，
      //   强制用户停留一定秒数（可在仓库配置，默认 10s），给出还原配置（主选项）、
      //   保持配置但不启动、仍然启动」。所以这里不记已读、没有开关、且弹窗不可关闭。
      try {
        const gate = await call('prelaunch_alerts');
        if (gate && gate.blocking) {
          for (const a of (gate.alerts || [])) {
            const hold = Math.max(0, Number(a.hold_seconds || gate.hold_seconds || 10));
            const lines = [a.title || '异常状态', ''];
            if (a.body) lines.push(a.body, '');
            if (a.url) lines.push(`详情：${a.url}`, '');
            lines.push('请先读完上面的内容，再做选择。');
            const choice = await showAlertGate({
              title: '⚠ 异常状态预警',
              message: lines.join('\n'),
              holdSeconds: hold,
              okText: '还原配置（关注入 + 清理游戏目录）',
              extraText: '保持配置但不启动',
              cancelText: '仍然启动',
            });
            await call('alert_action', a.id, choice);
            if (choice === 'restore') {
              logLine('   预警确认：已按你的选择「还原配置」（注入开关全部关闭、游戏目录第三方文件已备份移走）');
              logLine('   想恢复：设置页打开对应开关；游戏目录文件用「一键还原游戏本体」搬回');
              setStatus('已还原配置：注入已关闭、游戏目录已清理');
              if (a.url) { try { await call('open_external', a.url); } catch (err) { /* 忽略 */ } }
              return { needsSecondStart: false, gameReason: '已取消：异常状态预警，用户选择还原配置' };
            }
            if (choice === 'hold') {
              logLine('   预警确认：已按你的选择「保持配置但不启动」');
              setStatus('已取消启动（保持当前配置）');
              return { needsSecondStart: false, gameReason: '已取消：异常状态预警，用户选择保持配置但不启动' };
            }
            logLine('   预警确认：你选择「仍然启动」');
          }
        }
      } catch (err) {
        // 预警本身出问题（网络等）**不能挡住启动** —— 但要在日志里留痕
        logLine(`   异常状态检查失败（忽略，继续启动）: ${err.message || err}`);
      }
      // ①-a 文件守护：关键文件被反复删掉（多半是杀毒软件隔离）→ 提醒加白名单。
      //   用户 2026-10-01 决定「改到一键启动」（原先挂在打开管理器时）。
      //   时机特意放在自检补齐**之前**：紧接着 prepare_launch 就会把它补回来，
      //   "补了又被删"的现场在这一刻最清楚；打开管理器时只采样 + 记一行日志，不弹窗。
      try {
        const snapshot = await call('get_state');
        state.fileWatchdog = snapshot.file_watchdog || null;
      } catch (err) { /* 拿不到就不弹，绝不能挡住启动 */ }
      await maybeShowFileWatchdog();
      setStatus('正在初始化自检…');
      logLine('① 同步 XXMI 注入库 + 初始化自检（缺什么补什么）');
      const r = await call('prepare_launch');
      const checks = (r.initialize && r.initialize.checks) || [];
      for (const c of checks) {
        const flag = c.ok ? (c.fixed ? '已补齐' : '就绪') : '待处理';
        logLine(`   [${flag}] ${c.key} — ${c.message}`);
      }
      if ((r.actions || []).length) logLine(`   本次动作: ${r.actions.join(' / ')}`);
      for (const w of (r.warnings || [])) logLine(`   ⚠ ${w}`);
      const inj = r.injection || {};
      logLine(`   注入库(${inj.enabled ? '已开' : '未开'}): ${(inj.extra_libraries || '(空)').split('\n').join('  +  ')}`);
      if ($('init-status')) {
        $('init-status').textContent = checks
          .map((c) => `[${c.ok ? (c.fixed ? '已补齐' : '就绪') : '待处理'}] ${c.key}  ${c.message}`)
          .join('\n');
      }

      // ①-b 启动前的 Mod 冲突风险确认（用户 2026-09-30 要求）：
      //   自检发现资源冲突、或**这套组合以前崩过**（崩溃记忆）→ 先说清是什么冲突，
      //   再由用户决定「仍然启动 / 先去清理」。判据全是算好的事实，不是猜。
      //   ⚠ 本弹窗用 textContent 纯文本渲染，不要写 markdown 记号（会原样显示星号）。
      const risks = await call('prelaunch_risks');
      if (risks && risks.blocking) {
        const hasConflicts = (risks.conflicts || []).length > 0;
        const hasMemories = (risks.memories || []).length > 0;
        const rl = ['这套 Mod 组合有崩溃风险，建议先处理再启动：', ''];
        if ((risks.conflicts || []).length) {
          rl.push('【资源冲突】自检发现这些 Mod 覆盖同一批游戏资源：');
          for (const c of risks.conflicts) rl.push(`· ${c}`);
          rl.push('');
        }
        if ((risks.memories || []).length) {
          rl.push('【崩溃记忆】这套组合（或它的一部分）以前崩过：');
          for (const m of risks.memories) {
            rl.push(`· ${m.at_text || ''}　判定：${m.kind === 'mod_conflict' ? 'Mod 资源冲突' : '其它崩溃'}`);
            if ((m.mods || []).length) rl.push(`　当时的 Mod：${m.mods.join('、')}`);
          }
          rl.push('');
        }
        if (hasConflicts) {
          rl.push('建议：到「Mod 库」页把冲突项取消勾选一个 → 点「生成控制器」→ 再启动。');
        } else {
          rl.push('说明：这里**没有**判定成"资源冲突" —— 只是"这套组合以前崩过"的记录。');
          rl.push('上次到底为什么崩，看崩溃报告里的「归因」行：可能是 Mod，也可能是 DLSS5 的设置、显卡驱动或显存。');
        }
        rl.push('也可以选择仍然启动 —— 但游戏有可能在加载过程中闪退。');
        rl.push('');
        rl.push('（这里只做提示。如果进游戏后真的因为皮肤冲突崩了，崩溃弹窗里可以直接一键处理。）');
        // 按钮层级（用户 2026-09-30：「发现 mod 冲突风险应该先去清理才是右边的橙色主选项」）：
        //   最右 primary（橙色，默认聚焦）= 先去清理，不启动
        //   最左 = 仍然启动（冒险项）
        // ⚠ 2026-10-01 用户明确要求**这里只做提示**：「我说的自选保留一个 mod 应该在终末地
        //   崩溃而且是皮肤冲突导致的那里，**启动时那个只做提示，不需要只保留一个这个按钮**」
        //   —— 所以这个弹窗里不再有「一键关闭其中一个」，那个入口只在崩溃归因弹窗里。
        // 标题按**实际情况**说（2026-10-02 用户反馈：DLSS5 的 NRStyle 导致的崩溃被说成
        // "Mod 冲突风险"，他真去清理 Mod 了，白折腾）：只有**静态检出资源冲突**才叫冲突；
        // 只是"这套组合以前崩过"就照实说崩过，别冒充冲突。
        const riskTitle = hasConflicts
          ? (hasMemories ? '启动前发现 Mod 冲突风险（这套组合以前也崩过）' : '启动前发现 Mod 冲突风险')
          : '这套 Mod 组合以前崩过';
        const choice = await showModalDialog({
          title: riskTitle,
          message: rl.join('\n'),
          okText: hasConflicts ? '先去清理，不启动' : '先去调整，不启动',
          cancelText: '仍然启动',
        });
        if (choice === true) {
          logLine('   风险确认：你选择先去处理');
          setStatus(hasConflicts ? '已取消启动（先处理 Mod 冲突）' : '已取消启动（先换一套组合看看）');
          logLine('   已取消启动 —— 处理完再点「一键启动」即可');
          showTab('library');
          return { needsSecondStart: false, gameReason: '已取消：启动前检测到风险' };
        }
        logLine('   风险确认：你选择仍然启动');
      }

      logLine('② 拉起 XXMI Launcher，请在它的界面里点 Start 启动游戏');
      // ⚠ 2026-10-01：这一步必须自己兜住异常。以前没包 try/catch，`launch_official_gui`
      //   一抛错（例如 "没有配置可用的 XXMI Launcher 路径"）就冒泡出去，流程停在半路、
      //   界面看着像卡死。现在失败就地讲清"哪一步错了 + 去哪修"，然后干净退出。
      let launched;
      try {
        launched = await call('launch_official_gui');
      } catch (err) {
        const reason = err && err.message ? err.message : String(err);
        logLine(`   ✗ 拉起 XXMI 失败：${reason}`);
        logLine('   处理办法：到「依赖」页点「自动安装/更新」把内置 XXMI 装好'
          + '（或在设置页填你自己的 XXMI Launcher 路径），然后重新点「一键启动」。');
        setStatus('启动失败：' + reason);
        await showAlert(
          `拉起 XXMI 失败：\n${reason}\n\n到「依赖」页点「自动安装/更新」把内置 XXMI 装好，`
          + '或在设置页填上你自己的 XXMI Launcher 路径，然后重新点「一键启动」。',
          '启动失败'
        );
        return { needsSecondStart: false, gameReason: '启动失败：' + reason };
      }
      logLine(`   ${launched.message || 'XXMI Launcher 已打开'}`);
      logLine('进游戏后按 Home 打开 ReShade 面板检查插件。');
      setStatus('已拉起 XXMI，请在它的界面点 Start');
      // **等 XXMI 关闭之后再提示**（用户要求）：XXMI 把终末地拉起来后会自己退出，
      // 那一刻"游戏到底起没起来"才看得出来。没退出就继续等（最多 10 分钟）。
      logLine('③ 等 XXMI 退出（它拉起终末地后会自己关闭）…');
      setStatus('已在等 XXMI 退出…');
      const xxmiClosed = await waitXxmiClosed();
      logLine(xxmiClosed ? '   XXMI 已退出' : '   等了 10 分钟 XXMI 还没退出，先继续');

      // 判定"这一次算不算第一次启动"：
      //   * `xxmi_bootstrapped` —— 后端透传的硬标志，本次真的临时拉起过 XXMI 生成配置；
      //   * `onboarding_done` 为假 —— 用户还没走过/没跳过首次引导。
      // ⚠️ 不能用 `first_run`：它的判据是"三个内置组件里还有没装的"，只要有一个没装就
      //    永远为真 —— 那样每次点一键启动都会提示（用户 2026-09-29 反馈弹窗反复弹）。
      let firstUse = false;
      try {
        const fr = await call('first_run_state');
        firstUse = !(fr && fr.onboarding_done);
      } catch (err) { /* 探测失败不拦路 */ }
      // ④ XXMI 退出后再看终末地起没起来（用户要求：「可以在 xxmi 退出后检测终末地
      //    状态，如果在拉起后 10s 内退出就弹弹窗」）—— 这比"是不是第一次启动"准得多：
      //    之前出现过「显示 xxmi 已退出但并没有弹窗」，就是因为判据还是那两个标志。
      logLine('④ 检测终末地是否已启动（等它出现最多 30 秒，出现后再盯 10 秒）…');
      setStatus('正在检测终末地是否启动…');
      const game = await watchGameAfterXxmi();
      logLine(game.ok ? '   终末地已在运行' : `   ⚠ ${game.reason}`);
      // 游戏没起来**一定**提示；"第一次启动"（刚生成配置 / 还没走过引导）也提示一次
      return {
        needsSecondStart: !game.ok || !!r.xxmi_bootstrapped || firstUse,
        gameReason: game.reason || '',
      };
    };

    $('oneclick-launch-btn').onclick = async () => {
      const btn = $('oneclick-launch-btn');
      btn.disabled = true;
      try {
        const { needsSecondStart, gameReason } = await runOneClickLaunch();
        // 提示**放在拉起 XXMI 之后**（用户要求：「我说的第一次启动是在拉起 xxmi 之后
        // 再谈，选项应该是再次启动和先不启动」）。
        // 归因按用户 2026-09-29 的澄清写：**点 XXMI 的 Start 之后，终末地有概率不会
        // 正常启动** —— 不是"程序生成完配置自动关闭"那回事，也不是坏了；没起来就再
        // 启动一次。（"临时拉起 XXMI 生成配置"是另一件独立的事，只写进日志。）
        //
        // **只弹一次**：原先写成 `for (round < 3)` + 每轮重新判断，结果连弹三次
        // （用户 2026-09-29 反馈「按了再次启动那个弹窗会反复弹」）。现在点「再次启动」
        // 就重跑一遍，**重跑后不再提示**。
        if (needsSecondStart) {
          const again = await showModalDialog({
            title: '第一次启动有概率起不来 —— 没起来就再来一次',
            // ⚠️ 本弹窗用 textContent 纯文本渲染，不要写 markdown 记号（会原样显示星号）
            message: (gameReason ? `本次检测：${gameReason}\n\n` : '')
              + '点了 XXMI 界面里的 Start 之后，终末地有概率不会正常启动 —— 这是已知现象，不是坏了。\n\n'
              + '· 如果发现游戏没开起来（点了 Start 没反应，或过了几秒进程还没出现），\n'
              + '  再启动一次通常就好了\n'
              + '· 这个概率主要出现在第一次启动的时候\n'
              + '· 「再次启动」＝ 现在就帮你重跑一遍「一键启动」（会重新拉起 XXMI，\n'
              + '  你在它界面里再点一次 Start）\n'
              + '· 「先不启动」＝ 什么都不做，你随时可以自己再点「一键启动」\n',
            okText: '再次启动',
            cancelText: '先不启动',
          });
          if (again) {
            logLine('');
            logLine('按你的选择再启动一次…');
            await runOneClickLaunch();
          }
        }
      } catch (err) {
        logLine(`✗ 启动失败: ${err.message || err}`);
        setStatus(`启动失败: ${err.message || err}`);
      } finally {
        btn.disabled = false;
        await refreshFromState();
      }
    };
  }

  // 底座下两个插件各自独立开关（同一 ReShade 底座，靠移动 addon 文件实现）
  async function applyComponent(component, enabled) {
    const label = component === 'dlss5' ? 'DLSS5 神经渲染' : '第一人称';
    setStatus(`${enabled ? '正在启用' : '正在停用'}${label}…`);
    try {
      const r = await call('set_component_addon', component, enabled);
      // DLSS5 在非 RTX 50 系的机器上会被**后端拒绝**（根本出不了帧）——
      // 这时把开关弹回关闭状态，并把原因讲清楚，而不是让它"看着是开的"。
      if (r && r.ok === false && r.rejected) {
        logLine(`✗ ${label}无法启用：${r.message || ''}`);
        setStatus(`${label}无法启用`);
        await showAlert(r.message || '这台机器不支持 DLSS5 神经渲染。', '无法启用 DLSS5');
        await refreshFromState();
        return;
      }
      logLine(`${label}: ${enabled ? '已启用' : '已停用'}（移动 ${(r.moved || []).length} 个文件）`);
      if (r.warning) logLine(`⚠ ${r.warning}`);
      setStatus(`${label}${enabled ? '已启用' : '已停用'}`);
    } catch (err) {
      logLine(`✗ ${label}切换失败: ${err.message || err}`);
      setStatus(`切换失败: ${err.message || err}`);
    }
    await refreshFromState();
  }
  const dlss5Addon = $('cfg-dlss5-addon');
  if (dlss5Addon) dlss5Addon.onchange = () => applyComponent('dlss5', dlss5Addon.checked);
  const fpAddon = $('cfg-firstperson-addon');
  if (fpAddon) fpAddon.onchange = () => applyComponent('firstperson', fpAddon.checked);

  // 三件套（DLSS5 + 第一人称）注入开关
  const dlss5Toggle = $('cfg-dlss5-injection');
  if (dlss5Toggle) {
    dlss5Toggle.onchange = async () => {
      const enabled = dlss5Toggle.checked;
      setStatus(enabled ? '正在开启 DLSS5 注入…' : '正在关闭 DLSS5 注入…');
      try {
        await call('set_dlss5_injection', enabled);
        setStatus(enabled ? 'DLSS5 注入已开启' : 'DLSS5 注入已关闭');
      } catch (err) {
        dlss5Toggle.checked = !enabled;
        setStatus(`切换失败: ${err.message || err}`);
      }
      await refreshFromState();
    };
  }

  // 「皮肤 Mod」总开关：Mod 库页那一行与启动页那个滑块是**同一个开关**。
  // ⚠️ 2026-10-02 语义改了（用户实测）：「**efmi 关了直接终末地拉不起来**」—— 所以现在
  //    **不再去动注入库**（EFMI 的 d3d11.dll 一直注入），关掉它只表示"一个皮肤都不加载"；
  //    用户原话「**我手动关了所有皮肤 mod 就可以进了**」—— 真正该关的是皮肤，不是注入。
  async function applyModsMaster(enabled) {
    setStatus(enabled ? '正在开启皮肤 Mod…' : '正在关闭皮肤 Mod…');
    try {
      await call('save_config', { efmi_injection: enabled });
      // 立刻反映到 staging（后端走 effective_selected_mods：关掉 → 清空 Mods）
      const prepared = await call('prepare').catch(() => null);
      logLine(`皮肤 Mod: ${enabled ? '已开启' : '已关闭'}`
        + (prepared && prepared.patch_count !== undefined ? `  |  staging ${prepared.patch_count} 个` : ''));
      setStatus(enabled
        ? '皮肤 Mod 已开启（下次一键启动会按勾选装入）'
        : '皮肤 Mod 已关闭：一个皮肤都不加载（EFMI 照常注入，否则游戏起不来）');
    } catch (err) {
      logLine(`✗ 皮肤 Mod 总开关切换失败: ${err.message || err}`);
      setStatus(`切换失败: ${err.message || err}`);
    }
    await refreshFromState();
  }
  const modsMaster = $('cfg-third-party-mods');
  if (modsMaster) modsMaster.onchange = () => applyModsMaster(modsMaster.checked);
  const efmiToggle = $('cfg-efmi-injection');
  if (efmiToggle) efmiToggle.onchange = () => applyModsMaster(efmiToggle.checked);
  // 「强行关闭角色 Mod 互斥」：只改配置 + 立刻按新规则刷新列表与提示
  // （真正生效点有两处：前端勾选不再互相取消，后端生成控制器时不再按角色去重）
  const sameCharToggle = $('cfg-allow-same-character');
  if (sameCharToggle) {
    sameCharToggle.onchange = async () => {
      const enabled = sameCharToggle.checked;
      state.config.allow_same_character_mods = enabled;
      try {
        await call('save_config', { allow_same_character_mods: enabled });
        logLine(enabled
          ? '已强行关闭角色 Mod 互斥：同角色多个 Mod 可同时勾选（生成控制器时不再按角色去重）'
          : '已恢复角色 Mod 互斥：同角色只保留一个');
        setStatus(enabled ? '同角色互斥已关闭' : '同角色互斥已恢复');
      } catch (err) {
        logLine(`✗ 切换同角色互斥失败: ${err.message || err}`);
        setStatus(`切换失败: ${err.message || err}`);
      }
      await refreshFromState();      // 刷新提示文案与勾选状态
    };
  }
  // 初始化自检
  // 一键还原游戏本体：把游戏目录里所有第三方插件文件移走（先整体备份），恢复成原版状态
  if ($('game-restore-btn')) {
    $('game-restore-btn').onclick = async () => {
      if (!await showConfirm(
        '把终末地游戏目录里所有第三方插件文件移走、恢复成原版状态？\n\n'
        + '· 会先整体备份，随时可以用「从备份还原」搬回来\n'
        + '· loader proxy 会用系统原版文件补回\n'
        + '· Mod 库、配置与已装组件都不受影响',
        '一键还原游戏本体')) return;
      setStatus('正在还原游戏本体…');
      try {
        const result = await call('game_clean_backup_and_clean', true);
        await showAlert(result.message || (result.ok ? '游戏目录已还原为原版状态。' : '还原失败'),
                        '一键还原游戏本体');
      } catch (err) {
        await showAlert(`还原失败：${err.message || err}`, '一键还原游戏本体');
      }
      await refreshFromState();
    };
  }

  if ($('init-check-btn')) {
    $('init-check-btn').onclick = async () => {
      setStatus('正在做初始化自检…');
      const r = await call('ensure_initialized');
      const lines = [];
      for (const c of (r.checks || [])) {
        const flag = c.ok ? (c.fixed ? '已补齐' : '就绪') : '待处理';
        lines.push(`[${flag}] ${c.key}  ${c.message}`);
      }
      if ((r.actions || []).length) lines.push('', '本次补齐: ' + r.actions.join(' / '));
      if ((r.pending || []).length) lines.push('', `还有 ${r.pending.length} 项需要人工处理`);
      $('init-status').textContent = lines.join('\n');
      setStatus(r.ok ? '初始化自检通过' : `自检有 ${(r.pending || []).length} 项待处理`);
      await refreshFromState();
    };
  }

  // 乳摇插件（SecondaryMotion）：只留一个"启动插件界面"按钮，注入交给启动自检
  if ($('sbm-launch-btn')) {
    $('sbm-launch-btn').onclick = async () => {
      const r = await call('launch_secondary_motion');
      logLine(r.ok ? '乳摇管理器已启动' : `乳摇管理器启动失败: ${r.message || ''}`);
      setStatus(r.ok ? '乳摇管理器已启动' : (r.message || '启动失败'));
    };
  }

  // 乳摇开关：即时装 / 卸注入（不是只写配置）
  const sbmToggle = $('cfg-secondary_motion_injection');
  if (sbmToggle) {
    sbmToggle.onchange = async () => {
      const enabled = sbmToggle.checked;
      setStatus(enabled ? '正在安装乳摇注入…' : '正在卸载乳摇注入…');
      try {
        const r = enabled
          ? await call('secondary_motion_install')
          : await call('secondary_motion_uninstall');
        for (const a of (r.actions || [])) logLine(`乳摇: ${a}`);
        for (const w of (r.warnings || [])) logLine(`⚠ 乳摇: ${w}`);
        if (r.message) logLine(`⚠ 乳摇: ${r.message}`);
        const st = await call('secondary_motion_status');
        logLine(`乳摇注入: ${st.injected ? '已就位' : '未注入'} | plugin\\sbm.dll: ${st.plugin_exists ? '在' : '不在'}`);
        setStatus(enabled ? '乳摇注入已安装' : '乳摇注入已卸载');
      } catch (err) {
        sbmToggle.checked = !enabled;
        logLine(`✗ 乳摇切换失败: ${err.message || err}`);
        setStatus(`乳摇切换失败: ${err.message || err}`);
      }
      await call('save_config', { secondary_motion_injection: sbmToggle.checked });
    };
  }

  // 一键修复所有 Mod（实验性）：后台逐个修，前端轮询进度
  if ($('fix-all-mods-btn')) {
    $('fix-all-mods-btn').onclick = async () => {
      if (!await showModalDialog({
        title: '一键修复所有 Mod（实验性）',
        message: '会对库里每个 Mod 跑一次社区修复工具（B站 up 主 可可HXL，v1.5）：\n'
          + '· 每个 Mod 都会先整份备份，可单独「回滚修复」\n'
          + '· 修复在临时目录里进行，不会在 Mod 库或 Mods 里留备份与日志\n'
          + '· 已经修过的默认跳过\n'
          + '· 修完进游戏按 F10 刷新即可\n\n开始吗？',
        okText: '开始修复', cancelText: '先不修',
      })) return;
      const r = await call('fix_all_mods', true);
      logLine(`一键修复: ${r.message || ''}`);
      setStatus(r.message || '已开始修复…');
      if (!r.started && !r.already) { await refreshFromState(); return; }
      const timer = setInterval(async () => {
        let p = {};
        try { p = await call('fix_all_progress'); } catch (err) { return; }
        if ($('library-status')) {
          $('library-status').textContent = `修复中 ${p.current || 0}/${p.total || 0}：${p.name || ''}`;
        }
        if (!p.running) {
          clearInterval(timer);
          logLine(`一键修复完成: ${p.message || ''}`);
          for (const item of (p.results || []).filter(x => !x.ok)) {
            logLine(`  ✗ ${item.name}: ${item.message}`);
          }
          setStatus('一键修复完成');
          await refreshFromState();
        }
      }, 1500);
    };
  }

  // Endfield Poser：打开它自己的摆姿页 / 读它的日志 / 开关（开关是文件级可逆操作，不是只写配置）
  if ($('poser-webui-btn')) {
    $('poser-webui-btn').onclick = async () => {
      const r = await call('open_poser_web_ui');
      logLine(r.ok ? `已打开 Poser 摆姿页：${r.url}` : `Poser 摆姿页: ${r.message || r.url}`);
      setStatus(r.ok ? '已打开 Poser 摆姿页' : (r.message || '打开失败'));
    };
  }
  if ($('poser-log-btn')) {
    $('poser-log-btn').onclick = async () => {
      const r = await call('poser_log_tail', 40);
      logLine(`Poser 日志: ${r.path || '(未知路径)'}`);
      for (const line of (r.lines || [])) logLine(`  ${line}`);
      if (!r.ok) logLine(`⚠ ${r.message || '读取失败'}`);
    };
  }
  const poserToggle = $('cfg-poser_injection');
  if (poserToggle) {
    poserToggle.onchange = async () => {
      const enabled = poserToggle.checked;
      setStatus(enabled ? '正在启用 Endfield Poser…' : '正在停用 Endfield Poser…');
      try {
        if (enabled) {
          // 打开开关 = 要它在位：先补安装包与游戏目录里的文件，再让 dll 生效
          const r = await call('poser_install');
          for (const a of (r.actions || [])) logLine(`Poser: ${a}`);
          for (const w of (r.warnings || [])) logLine(`⚠ Poser: ${w}`);
          if (r.message) logLine(`⚠ Poser: ${r.message}`);
          const st = await call('poser_status');
          logLine(`Poser: ${st.installed ? 'plugin\\poser.dll 已就位' : '未就位'} | loader ${st.loader_kind || '不在位'} | 表情校准 ${st.face_count || 0} 份`);
          setStatus(r.ok ? 'Endfield Poser 已启用' : (r.message || 'Poser 未就绪'));
        } else {
          const r = await call('set_poser_enabled', false);
          logLine(r.ok ? `Poser: ${r.message}` : `⚠ Poser: ${r.message}`);
          setStatus(r.ok ? 'Endfield Poser 已停用（下次进游戏不加载）' : (r.message || '停用失败'));
        }
      } catch (err) {
        poserToggle.checked = !enabled;
        logLine(`✗ Poser 切换失败: ${err.message || err}`);
        setStatus(`Poser 切换失败: ${err.message || err}`);
      }
      await call('save_config', { poser_injection: poserToggle.checked });
    };
  }

  // 右上角：版本号 + 更新检测（对比 GitHub release 的 tag）
  // 项目链接（仓库 / issue / 发布页）只在这里解析一次，界面各处共用
  const appLinks = {};

  function fillRepoLinks(repo) {
    if (!repo) return;
    const base = String(repo).replace(/\/+$/, '');
    appLinks.repo = base;
    appLinks.issues = `${base}/issues/new/choose`;
    appLinks.releases = `${base}/releases`;
    window.__mcLinks = appLinks;      // 「怎么反馈」弹窗要用它（见 showFeedbackModal）
    const pairs = [
      ['about-repo-link', appLinks.repo],
      ['about-issues-link', appLinks.issues],
      ['about-releases-link', appLinks.releases],
      ['crash-issue-link', appLinks.issues],
      ['feedback-issue-link', appLinks.issues],
    ];
    for (const [id, url] of pairs) {
      const el = $(id);
      if (el) { el.href = url; el.textContent = url; }
    }
  }

  // 界面上所有网址都**直接点开**（用户 2026-10-01 要求：「程序内所有给网址做了打开键的，
  // 全部去掉，点击网址就可以直接打开了」）—— 用事件委托，动态填进去的链接（仓库/issue/
  // 发布页、弹窗里的反馈地址）也一并生效，不必逐处绑 onclick，也不会漏。
  document.addEventListener('click', (event) => {
    const anchor = event.target && event.target.closest ? event.target.closest('a[href^="http"]') : null;
    if (!anchor) return;
    event.preventDefault();          // 别让 WebView 把界面导航走
    call('open_external', anchor.href).catch(() => {});
  });

  async function initAppUpdate() {
    const btn = $('app-update-btn');
    if (!btn) return;
    try {
      const info = await call('get_app_info');
      btn.textContent = `v${info.version}`;
      btn.dataset.version = info.version;
      fillRepoLinks(info.repo);
    } catch (err) {
      btn.textContent = 'v?';
    }
    // 静默检查一次（有缓存，不会每次都打网络）
    try {
      const r = await call('check_app_update', true);
      if (r.update_available) {
        btn.classList.add('has-update');
        btn.textContent = `v${r.current} → v${r.latest}`;
        btn.title = `发现新版本 v${r.latest}，点这里更新`;
        setStatus(`发现新版本 v${r.latest}`);
      } else {
        btn.title = r.error ? `更新检查：${r.error}` : `已是最新（v${r.current}）`;
      }
    } catch (err) {
      /* 离线时保持安静 */
    }
  }

  async function runAppUpdate(checkOnly) {
    setStatus('正在检查程序更新…');
    const r = await call('check_app_update', false);
    const lines = [
      `当前版本：v${r.current}`,
      `最新版本：v${r.latest || '未知'}${r.update_available ? '  【有新版】' : ''}`,
      r.frozen ? `程序路径：${r.exe}` : '运行模式：源码（自动替换不可用，请 git pull）',
    ];
    if (r.published) lines.push(`发布时间：${r.published}`);
    if (r.asset) lines.push(`更新包：${r.asset}  ${((r.asset_size || 0) / 1048576).toFixed(1)} MB`);
    if (r.notes) lines.push('', '更新说明：', r.notes.slice(0, 800));
    if (r.error) lines.push('', `错误：${r.error}`);
    if ($('update-status')) $('update-status').textContent = lines.join('\n');

    if (r.error) { setStatus('检查更新失败'); return r; }
    if (checkOnly || !r.update_available) {
      setStatus(r.update_available ? `有新版 v${r.latest}` : '已是最新');
      if (!checkOnly) await showAlert(`已是最新版本 v${r.current}`);
      return r;
    }
    if (!await showConfirm(`发现新版本 v${r.latest}（当前 v${r.current}）\n\n现在下载吗？\n· 下载完成后会**再问一次**：立即重启安装，还是稍后\n· 更新期间请不要手动打开程序（替换过程中会被打断）\n· config.json 与 Mod 库不受影响\n· 失败会自动回滚旧版本\n\n进度会显示在「依赖」页`)) return r;

    if (!r.frozen) {
      // 源码运行模式没法替换自己：只下载更新包，然后提示手动 git pull
      setStatus('正在下载更新包…');
      const dl = await call('download_app_update');
      if (!dl.ok) {
        await showAlert(`下载失败：${dl.message || '未知错误'}`);
        setStatus('下载失败');
        return r;
      }
      await showAlert(`更新包已下载到：\n${dl.path}\n\n源码运行模式不会自动替换，请手动更新（git pull）。`);
      setStatus('已下载（源码模式）');
      return r;
    }
    // 交给依赖页那条链路：切页 + 进度条 + 自动重启
    await startAppUpdateFromDep();
    return r;
  }

  if ($('app-update-btn')) {
    $('app-update-btn').onclick = () => runAppUpdate(false);
  }
  if ($('update-app-check-btn')) {
    $('update-app-check-btn').onclick = () => runAppUpdate(true);
  }
  initAppUpdate();

  // 组件更新
  if ($('update-check-btn')) {
    $('update-check-btn').onclick = async () => {
      setStatus('正在检查组件更新…');
      const r = await call('check_component_updates');
      const rs = r.reshade || {};
      const sm = r.secondary_motion || {};
      const d5 = r.dlss5 || {};
      const lines = [
        `ReShade 底座 : 当前 ${rs.current || '?'}  →  最新 ${rs.latest || '?'}  ${rs.update_available ? '【有新版】' : ''}`,
      ];
      if (rs.note) lines.push(`   ${rs.note}`);
      lines.push(`乳摇插件     : 当前 ${sm.current || '?'}  →  最新 ${sm.latest || '?'}  ${sm.update_available ? '【有新版】' : ''}`);
      if (sm.asset) lines.push(`   ${sm.asset}  ${((sm.size || 0) / 1048576).toFixed(1)} MB  ${sm.published || ''}`);
      const po = r.poser || {};
      lines.push(`Endfield Poser: 当前 ${po.current || '未安装'}  →  最新 ${po.latest || '?'}  ${po.update_available ? '【有新版】' : ''}${po.prerelease ? '（预发布）' : ''}`);
      if (po.asset) lines.push(`   ${po.asset}  ${((po.size || 0) / 1048576).toFixed(1)} MB  ${po.published || ''}`);
      if (po.license) lines.push(`   上游许可 ${po.license}：只下载它的官方安装包，不随包分发`);
      const fd = d5.dlss5_feed || {};
      if (fd.latest) {
        lines.push(`DLSS5-Feeder : 当前 ${fd.current || '未安装'}  →  最新 ${fd.latest}  ${fd.update_available ? '【可更新】' : ''}`);
      }
      const im = d5.immersse || {};
      if (im.latest) {
        lines.push(`iMMERSE      : 当前 ${im.current || '未安装'}  →  最新 ${im.latest}  ${im.update_available ? '【可更新】' : ''}`);
      }
      if ((r.errors || []).length) lines.push('错误: ' + r.errors.join(' | '));
      $('update-status').textContent = lines.join('\n');
      setStatus('更新检查完成');
    };
    // 一键装齐所有"不随包分发"的组件（含随包资产展开 + XXMI/EFMI + DLSS5 组件 + 乳摇）
    if ($('update-all-btn')) {
      $('update-all-btn').onclick = async () => {
        if (!await showConfirm('将自动安装/更新所有组件：\n\n· 随包资产展开（DLSS 运行库、DLSS5 组件包）\n· XXMI Launcher / XXMI 库 / EFMI\n· ReShade 底座、DLSS5-Feeder、iMMERSE shader\n· 乳摇插件\n· Endfield Poser（摆姿 / MMD，从官方 Release 下载，上游 AGPL-3.0）\n\n需要联网，继续？')) return;
        setStatus('正在一键安装/更新全部组件…');
        await startFullUpdate(false, $('update-status'));
        setStatus('全部组件处理完成');
      };
    }
    $('update-reshade-btn').onclick = async () => {
      if (!await showConfirm('将从 reshade.me 下载官方 ReShade Addon，替换 runtime\\dlss5\\d3d12.dll（旧版自动备份）。\n官方新版可能与 DLSS5 插件不兼容，出问题可用备份回退。继续？')) return;
      setStatus('正在更新 ReShade 底座…');
      const r = await call('update_component', 'reshade');
      $('update-status').textContent = r.ok ? `ReShade 已更新到 ${r.version}\n${r.note || ''}` : (r.message || '更新失败');
      setStatus(r.ok ? 'ReShade 底座已更新' : 'ReShade 更新失败');
    };
    // 乳摇插件的更新已并入「自动安装/更新」（依赖列表里的 secondary_motion 项）
  }
  // 下载加速 / 线路：按需临时启用，用完即放（不常驻、不改系统）
  ['cfg-download_boost', 'cfg-download_line'].forEach((id) => {
    const el = $(id);
    if (!el) return;
    el.onchange = async () => {
      await call('set_download_settings',
        $('cfg-download_boost').value, $('cfg-download_line').value);
      await refreshDownloadStatus();
      setStatus('下载设置已更新');
    };
  });
  if ($('clear-download-lines-btn')) {
    $('clear-download-lines-btn').onclick = async () => {
      await call('clear_download_lines');
      await refreshDownloadStatus();
      setStatus('线路记录已清除');
    };
  }

  // 游戏目录体检 / 备份净化 / 还原（净化前一律先整体备份，只移动不删除）
  if ($('game-audit-btn')) {
    $('game-audit-btn').onclick = async () => {
      setStatus('正在体检游戏目录…');
      const r = await call('game_clean_audit');
      const mi = await call('game_multi_instance_status');
      const lines = [
        `游戏目录：${r.game_dir || '未定位'}`,
        `结论：${r.clean ? '干净（原版状态）' : `发现 ${(r.findings || []).length} 项非原版文件`}`,
      ];
      for (const f of (r.findings || [])) {
        lines.push(`  · [${f.label}] ${f.relative}${f.size ? '  ' + (f.size / 1024).toFixed(1) + ' KB' : ''}`);
        if (f.detail) lines.push(`      ${f.detail}`);
      }
      lines.push(`多开状态：${mi.running ? '终末地正在运行（' + (mi.processes || []).join(', ') + '）' : '没有检测到终末地在运行'}`);
      $('game-clean-status').textContent = lines.join('\n');
      setStatus('体检完成');
    };
  }
  if ($('game-clean-btn')) {
    $('game-clean-btn').onclick = async () => {
      if (!await showConfirm('将先**完整备份**游戏目录里所有非原版文件，再把它们移走（proxy 会用系统原版补回）。\n\n· 只移动不删除，随时可「从备份还原」\n· 净化后终末地本体 = 原版状态，适合做对照测试\n\n继续？')) return;
      setStatus('正在备份并净化游戏目录…');
      const r = await call('game_clean_backup_and_clean', true);
      const lines = [r.message || ''];
      for (const m of (r.moved || [])) lines.push(`  移走 [${m.label}] ${m.relative}`);
      for (const m of (r.restored_modules || [])) lines.push(`  补回系统模块 ${m.name}（来源 ${m.source}）`);
      for (const e of (r.errors || [])) lines.push(`  ⚠ ${e}`);
      $('game-clean-status').textContent = lines.join('\n');
      setStatus(r.ok ? '游戏目录已净化' : '净化完成但有警告');
    };
  }
  if ($('game-clean-restore-btn')) {
    $('game-clean-restore-btn').onclick = async () => {
      const list = await call('game_clean_backups');
      const backups = list.backups || [];
      if (!backups.length) { await showAlert('还没有任何游戏目录备份'); return; }
      const latest = backups[0];
      if (!await showConfirm(`从最近的备份还原游戏目录？\n\n备份时间：${latest.stamp}\n包含 ${latest.entries} 项\n\n会把之前移走的文件搬回游戏目录。`)) return;
      setStatus('正在还原…');
      const r = await call('game_clean_restore', '');
      const lines = [r.message || ''];
      for (const x of (r.restored || [])) lines.push(`  还原 ${x}`);
      for (const e of (r.errors || [])) lines.push(`  ⚠ ${e}`);
      $('game-clean-status').textContent = lines.join('\n');
      setStatus(r.ok ? '已从备份还原' : '还原完成但有警告');
    };
  }

  $('cfg-theme').onchange = async () => {
    applyTheme($('cfg-theme').value);
    await call('save_config', { theme: $('cfg-theme').value });
  };
  $('theme-toggle').onclick = async () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    applyTheme(next);
    await call('save_config', { theme: next });
    state.config.theme = next;
  };
  $('autodetect-btn').onclick = async () => {
    const s = await call('get_state');
    if (s.detected_xxmi) {
      $('cfg-xxmi_launcher').value = s.detected_xxmi;
      await saveConfig();
      $('settings-status').textContent = '已自动检测并保存 XXMI 路径';
    } else {
      await showAlert('没有自动找到 XXMI Launcher，请点击“选择 XXMI Launcher”手动指定。');
    }
  };
  $('download-reshade-btn').onclick = async () => {
    if (!await showConfirm('从 reshade.me 下载官方 ReShade Addon 并放到 runtime/reshade/？')) return;
    $('settings-status').textContent = '下载并解压 ReShade...';
    const result = await call('download_reshade');
    $('cfg-reshade_dll').value = result.dll;
    await saveConfig();
    $('settings-status').textContent = 'ReShade 已就绪：' + result.dll;
  };
  $('open-root-btn').onclick = async () => {
    const info = await call('log');
    await call('open_path', info.runtime);
  };
  // 「选择…」按钮已按用户要求全部移除（设置页改成直接输入 + 一个「一键检测全部」），
  // 所以这里不再绑定它们；需要弹选择框时用设置页上保留的「自动检测 XXMI」。
  $('rollback-btn').onclick = async () => {
    if (!await showConfirm('将删除 EndfieldModControllerManaged staging，并恢复可用的 d3dx_user.ini / XXMI 配置备份。继续？')) return;
    const result = await call('rollback');
    $('settings-status').textContent = JSON.stringify(result);
  };
  document.querySelectorAll('[data-open]').forEach(btn => btn.onclick = () => openPath(btn.dataset.open));
}

let __booted = false;
function splashMsg(text) {
  const el = $('splash-msg');
  if (el) el.textContent = text;
}
// 加载页至少显示这么久：WebView2 首次渲染要 1 秒上下，一就绪就立刻收起的话
// 用户根本看不到加载页，只看到"白屏闪一下"（2026-10-01 实测定位）。
const SPLASH_MIN_MS = 700;
const __splashStart = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
function splashDone() {
  const el = $('splash');
  if (!el) return;
  const now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
  const wait = Math.max(0, SPLASH_MIN_MS - (now - __splashStart));
  setTimeout(() => el.classList.add('hidden'), wait);
}
// 看门狗：无论初始化成功与否，18 秒后强制收起加载页。
// 否则任何一处 JS 异常都会让界面永远停在"正在扫描 Mod 库…"。
setTimeout(() => {
  const el = $('splash');
  if (el && !el.classList.contains('hidden')) {
    el.classList.add('hidden');
    setStatus('初始化超时：界面已放行，请看日志窗的诊断信息');
    try { logLine('[WARN] 初始化超过 18 秒未完成，已强制收起加载页（详见上方诊断）'); } catch (e) { /* ignore */ }
  }
}, 18000);
async function boot() {
  if (__booted) return;
  __booted = true;
  const diag = [];
  // **先把加载页画出来**再做别的：`bind()` 会同步操作大量 DOM，后面紧跟 await 又会
  // 让出主线程 —— 不先让浏览器绘制一次的话，用户看到的就是"窗口亮着一片空白，
  // 然后直接跳到主界面"，加载页几乎不存在（2026-10-01 实测定位到这一点）。
  await new Promise((resolve) => {
    if (typeof requestAnimationFrame === 'function') {
      requestAnimationFrame(() => setTimeout(resolve, 0));
    } else {
      setTimeout(resolve, 0);
    }
  });
  splashMsg('正在绑定界面…');
  try { bind(); diag.push('bind ✓'); } catch (err) { diag.push(`bind ✗ ${err.message || err}`); console.error('bind 失败', err); }
  try { initTour(); } catch (err) { console.error('initTour 失败', err); }
  splashMsg('正在读取配置…');
  try {
    await refreshFromState();
    diag.push('state ✓');
  } catch (err) {
    diag.push(`state ✗ ${err.message || err}`);
    console.error('refreshFromState 失败', err);
    setStatus(`状态刷新失败: ${err.message || err}`);
  }
  splashMsg('正在扫描 Mod 库…（首次约几秒）');
  await new Promise((r) => setTimeout(r, 30));   // 让上一条提示先绘制出来
  try {
    await scan();
    diag.push(`scan ✓ ${state.mods.length} 个 Mod`);
  } catch (err) {
    diag.push(`scan ✗ ${err.message || err}`);
    console.error('scan 失败', err);
    setStatus(`Mod 扫描失败: ${err.message || err}`);
  }
  try { await auditGameInjections(true); } catch (err) { diag.push(`audit ✗ ${err.message || err}`); }
  if ($('library-status')) {
    $('library-status').textContent = `已发现 ${state.mods.length} 个 Mod，按角色分组显示`;
    if (!state.mods.length) $('library-status').textContent = `未扫描到 Mod。诊断: ${diag.join(' | ')}`;
  }
  if ($('console-log')) {
    const el = $('console-log');
    if (el.dataset.ready !== '1') {
      el.textContent = `[启动诊断] ${diag.join('  |  ')}\n点「一键启动」开始，或先到 Mod 库页勾选要用的 Mod。\n`;
      el.dataset.ready = '1';
    }
    paintLog(el);
  }
  paintLog($('log-text'));
  splashDone();
  // 首屏已经出来了：这时才告诉后端"可以开始后台全盘探测了"。
  // 否则那些扫描会和 WebView2 窗口初始化抢磁盘/GIL，从零启动时窗口要等约 10 秒
  // 才可见（2026-10-01 实测定位）。
  try { call('ui_ready').catch(() => {}); } catch (err) { /* 忽略 */ }
  startCrashPolling();
  // 上次更新选了"稍后"：启动后过一会儿再问一次（延后询问，不拖慢首屏）
  setTimeout(async () => {
    try {
      const pending = await call('pending_update');
      if (pending && pending.pending) {
        await askApplyUpdate(`已下载 v${pending.latest || '新版'} 的更新`);
      }
    } catch (err) { /* 忽略：不影响正常使用 */ }
  }, 1500);
  // 第一次使用（未初始化、且没走过引导）：**先问要不要引导**，而不是直接推一键启动。
  // 用户 2026-10-01 要求：「不要上来就一键启动，应该问是否需要引导，然后是和跳过，
  // 引导应该先调到依赖页，箭头指一键更新下载介绍并建议点击，然后说一下能拖 zip 文件
  // 进来，然后建议一键启动并同时说明能在设置页一键还原」。
  setTimeout(async () => {
    try {
      const fr = await call('first_run_state');
      if (!fr || fr.onboarding_done) return;
      const missing = (fr.missing_components || []).join('、');
      const start = await showModalDialog({
        title: '要不要看一下使用引导？',
        message: (fr.first_run
          ? `检测到本程序还没完成初始化${missing ? `（当前缺少：${missing}）` : ''}。\n\n`
          : '') +
          '引导会带你走一遍最关键的几步（约 1 分钟）：\n'
          + '· 在「依赖」页一键装齐全部组件\n'
          + '· 在「Mod 库」页把压缩包（.zip / .7z / .rar）拖进来导入 Mod\n'
          + '· 一键启动，以及出问题时怎么一键还原\n',
        okText: '开始引导',
        cancelText: '跳过',
      });
      if (start) tourShow(0);
      else tourFinish();       // 跳过也记下来，下次不再问
    } catch (err) { /* 忽略 */ }
  }, 1200);
  // 角色识别不确定的 Mod：弹窗让用户选（延后一点，别和启动流程抢时间）
  setTimeout(() => { startCharacterCheck(); }, 1500);
  // 公告：稍后再检查一次。公告是**后台线程**拉的（通常首屏之后 1~3 秒才到），
  // 所以不能只在一个固定时刻看一次；refreshFromState 里也会调同一个函数（幂等）。
  // 这里保留一个延迟入口，顺便错开引导(1.2s)/更新询问(1.5s)/角色识别(1.5s) 的弹窗。
  setTimeout(() => { maybeShowAnnouncements(); }, 2500);
  // 注意：文件守护**不在启动时弹**（用户 2026-10-01 决定改到「一键启动」时弹），
  // 所以这里没有它的兜底入口 —— 见 runOneClickLaunch() 里那一段。
}

// ── 崩溃包提示：轮询后端，发现新的崩溃包就弹窗给出路径 ──
let __crashPoll = null;
function startCrashPolling() {
  if (__crashPoll) return;
  const tick = async () => {
    try {
      const r = await call('crash_bundle_status');
      if (r && r.fresh) showCrashModal(r.fresh);
    } catch (err) { /* 忽略：后端可能正在忙 */ }
  };
  __crashPoll = setInterval(tick, 8000);
  setTimeout(tick, 3000);
}

function showCrashModal(bundle) {
  const modal = $('crash-modal');
  if (!modal) return;
  const cause = bundle.cause || {};
  const isConflict = cause.kind === 'mod_conflict';
  // 标题/说明/按钮按**归因**切换：确定是 Mod 冲突就走另一套（用户要求区分开）
  if ($('crash-modal-title')) $('crash-modal-title').textContent = cause.title || '检测到终末地异常退出';
  if ($('crash-modal-hint')) {
    if (isConflict) {
      $('crash-modal-hint').textContent = '自检记录到 Mod 资源冲突，游戏随后在加载过程中退出。建议先清冲突（这一步最可能一步解决），诊断包仍会照常生成。';
    } else {
      $('crash-modal-hint').textContent = '已自动把「控制器日志 + 终末地自己的日志 + 崩溃转储」收集并打包。把这个 zip 发到本项目的 issue 或 QQ 群即可，里面已经包含定位所需的一切（记得附上现象：崩溃前你在做什么）。';
    }
  }
  if ($('crash-conflict-block')) {
    $('crash-conflict-block').style.display = isConflict ? '' : 'none';
    if ($('crash-conflict-detail')) {
      const list = (cause.conflicts || []).filter(Boolean);
      $('crash-conflict-detail').textContent = list.length
        ? list.join('\n')
        : (cause.detail || '（这次自检没留下细节：到 Mod 库页点一次「生成控制器」会重新检查）');
    }
  }
  const gotoLibrary = $('crash-goto-library');
  if (gotoLibrary) {
    gotoLibrary.style.display = isConflict ? '' : 'none';
    gotoLibrary.onclick = () => { modal.classList.add('hidden'); showTab('library'); };
  }
  // 「一键关闭其中一个（自行选择）」（用户 2026-10-01 要求）：点了之后**先关掉这个弹窗**，
  // 再弹「选择要保留的 Mod」——那里每组冲突一个下拉框，选完自动取消勾选其余并重新生成控制器。
  const resolveButton = $('crash-resolve-conflicts');
  if (resolveButton) {
    resolveButton.style.display = isConflict ? '' : 'none';
    resolveButton.onclick = async () => {
      modal.classList.add('hidden');
      await showConflictResolveModal();
    };
  }
  if ($('crash-modal-close')) {
    // 冲突时把主按钮让给「去 Mod 库清理冲突」，关闭按钮降为次要
    $('crash-modal-close').className = isConflict ? '' : 'primary';
    $('crash-modal-close').textContent = isConflict ? '先看看，稍后自己处理' : '知道了';
  }
  $('crash-dir').textContent = bundle.dir || '(无)';
  $('crash-zip').textContent = bundle.zip || '(未打包成功，请直接压缩上面的文件夹)';
  const lines = [
    `时间      : ${bundle.created_at || '-'}`,
    `崩溃判定  : ${bundle.crashed ? 'CrashSight 记录到异常' : '未检测到崩溃记录（可能是正常退出）'}`,
    `归因      : ${bundle.crashed
      ? (cause.title || '其它原因（看包里的 controller-crash-report.log）')
      : '未崩溃'}`,
    `收进包的终末地日志 (${(bundle.game_logs || []).length} 份):`,
    ...(bundle.game_logs || []).slice(0, 12).map((n) => `   ${n}`),
    '',
    '包里还带了 dlss5-feed.log / ReShade.ini（DLSS5 现场）与 cause.json（归因）。',
    '反馈建议：把 zip 里的内容贴到 GitHub issue，或加 QQ 群 '
      + `${FEEDBACK_QQ}（验证答案：${FEEDBACK_QQ_ANSWER}）发在群里；两种方式都请附上现象。`,
  ];
  $('crash-summary').textContent = lines.join('\n');
  modal.classList.remove('hidden');
  if ($('crash-open-dir')) $('crash-open-dir').onclick = () => call('open_path_in_explorer', bundle.dir || '');
  if ($('crash-open-zip')) $('crash-open-zip').onclick = () => call('open_path_in_explorer', bundle.zip || bundle.dir || '');
  if ($('crash-copy-zip')) {
    $('crash-copy-zip').onclick = async () => {
      const text = bundle.zip || bundle.dir || '';
      try { await navigator.clipboard.writeText(text); setStatus('zip 路径已复制'); }
      catch (err) { setStatus(`复制失败，请手动复制: ${text}`); }
    };
  }
  if ($('crash-modal-close')) $('crash-modal-close').onclick = () => modal.classList.add('hidden');
  if ($('crash-copy-qq')) {
    $('crash-copy-qq').onclick = async () => {
      try { await navigator.clipboard.writeText(`${FEEDBACK_QQ}（验证答案：${FEEDBACK_QQ_ANSWER}）`); setStatus('QQ 群号已复制'); }
      catch (err) { setStatus(`复制失败，请手动复制: ${FEEDBACK_QQ}`); }
    };
  }
}

// ── 角色识别不确定时弹窗让用户选择 ──────────────────────────────
// 用户需求原话：「如果不确定就弹窗让用户选择」。
// 识别错会让「同角色互斥」失效 —— 两个同角色 Mod 同时生效会导致游戏崩溃，
// 所以这种情况不猜，交用户定夺；选完写进该 Mod 的 mod.meta.json，以后不再问。
let __charPending = [];
let __charKnown = [];

async function startCharacterCheck(focusId) {
  let data;
  try {
    data = await call('pending_characters');
  } catch (err) {
    return;                       // 后端可能正忙，静默跳过
  }
  if (!data || !data.pending || !data.pending.length) return;
  __charPending = data.pending;
  __charKnown = data.known || [];
  const pending = focusId ? data.pending.filter((m) => m.id === focusId) : data.pending;
  showCharacterModal({ pending: pending.length ? pending : data.pending, known: __charKnown });
}

function showCharacterModal(data) {
  const modal = $('char-modal');
  const list = $('char-pending-list');
  if (!modal || !list) return;

  list.innerHTML = '';
  for (const item of data.pending) {
    const row = document.createElement('div');
    row.style.cssText = 'margin:8px 0;padding:9px 11px;border-radius:6px;background:rgba(128,128,128,.12)';
    const why = item.confidence === 'none'
      ? '名字里没找到任何角色名'
      : '出现了多个角色名，分不清哪个才是主体';
    const first = (item.guess || (item.candidates || [])[0] || '');
    const all = [...new Set([...(item.candidates || []), ...(data.known || [])])].filter(Boolean);
    const opts = all
      .map((n) => `<option value="${escapeHtml(n)}"${n === first ? ' selected' : ''}>${escapeHtml(n)}</option>`)
      .join('');
    const guessLine = item.guess
      ? `<div class="hint" style="margin:2px 0 0">预识别：<b>${escapeHtml(item.guess)}</b>（按"和哪个角色相关字数最多"猜的，请确认）</div>`
      : '';
    row.innerHTML = `
      <div style="font-weight:600">${escapeHtml(item.name)}</div>
      <div class="hint" style="margin:2px 0 6px">${escapeHtml(why)}</div>
      <select data-char-select="${escapeHtml(item.id)}" style="min-width:220px">
        <option value="">（请选择角色）</option>
        ${opts}
      </select>
      ${guessLine}
    `;
    list.appendChild(row);
  }
  modal.classList.remove('hidden');

  if ($('char-modal-skip')) $('char-modal-skip').onclick = () => modal.classList.add('hidden');
  if ($('char-modal-save')) {
    $('char-modal-save').onclick = async () => {
      let saved = 0;
      for (const sel of list.querySelectorAll('select[data-char-select]')) {
        if (!sel.value) continue;
        try {
          const r = await call('set_mod_character', sel.dataset.charSelect, sel.value);
          if (r && r.ok) saved += 1;
        } catch (err) { /* 单个失败不阻断其余 */ }
      }
      modal.classList.add('hidden');
      if (saved) {
        setStatus(`已确认 ${saved} 个 Mod 的角色`);
        try { await scan(); } catch (err) { /* 刷新失败不影响已保存的结果 */ }
      } else {
        setStatus('没有选择任何角色');
      }
    };
  }
}

// 点卡片上的「角色待确认」标记 → 只针对那个 Mod 打开弹窗
document.addEventListener('click', (event) => {
  const pick = event.target && event.target.closest ? event.target.closest('[data-char-pick]') : null;
  if (pick) startCharacterCheck(pick.dataset.charPick);
});

window.addEventListener('pywebviewready', boot);
// 兜底：某些时序下 pywebviewready 可能早于脚本绑定而丢失，DOM 就绪后补一次
window.addEventListener('DOMContentLoaded', () => setTimeout(boot, 1500));
