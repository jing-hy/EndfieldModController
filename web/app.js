const state = { config: {}, mods: [], dependency_report: {}, selected: new Set(), lastPrepare: null };

function applyTheme(theme) {
  const value = theme === 'light' ? 'light' : 'dark';
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
function showModalDialog({ title, message, okText = '确定', cancelText = '取消', showCancel = true }) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal';
    wrap.innerHTML = '<div class="modal-content" style="width:min(560px,92vw)">'
      + '<div class="modal-header"><h3></h3></div>'
      + '<pre class="modal-body"></pre>'
      + '<div class="modal-actions"></div></div>';
    wrap.querySelector('h3').textContent = title;
    wrap.querySelector('.modal-body').textContent = message;
    const actions = wrap.querySelector('.modal-actions');
    let settled = false;
    const onKey = (event) => {
      if (event.key === 'Escape') finish(false);
      if (event.key === 'Enter') finish(true);
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
        <h3>${group}</h3>
        <span class="hint">${mods.length} 个 Mod · 已启用 ${enabledCount}</span>
      </div>
    `;
    const grid = document.createElement('div');
    grid.className = 'mod-list';
    for (const mod of mods) {
      const dependency = mod.kind === 'dependency' || mod.kind === 'tool';
      // 角色识别不确定时（low/none）在卡片上打个标记，点它就能选择
      const needConfirm = !dependency && (mod.char_confidence === 'low' || mod.char_confidence === 'none');
      const card = document.createElement('div');
      card.className = 'mod-card' + (dependency ? ' disabled' : '');
      const checked = dependency || state.selected.has(mod.id);
      card.innerHTML = `
        <div class="cover" data-cover-box="${mod.id}"><span>无预览图</span></div>
        <div class="name">${mod.name}</div>
        <div class="meta">${mod.kind} · id=${mod.id}</div>
        ${needConfirm ? '<div class="meta" style="color:#d98a1f;cursor:pointer" data-char-pick="' + mod.id + '">⚠ 角色待确认 —— 点此选择</div>' : ''}
        <label class="switch">
          <input type="checkbox" data-mod-toggle value="${mod.id}" ${checked ? 'checked' : ''} ${dependency ? 'disabled' : ''}>
          <span class="slider"></span>
        </label>
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
      if (cb.checked) {
        state.selected.add(mod.id);
        for (const other of state.mods) {
          if (other.id === mod.id) continue;
          if (other.kind !== 'character') continue;
          if ((other.conflict_group || other.group) !== groupKey) continue;
          state.selected.delete(other.id);
          const otherToggle = root.querySelector(`input[data-mod-toggle][value="${CSS.escape(other.id)}"]`);
          if (otherToggle) otherToggle.checked = false;
        }
      } else {
        state.selected.delete(mod.id);
      }
      updateGroupHeader(cb.closest('.group-block'), groupKey);
      saveSelection();
    };
  });
  $('library-status').textContent = `已发现 ${state.mods.length} 个 Mod，按角色分组显示`;
  loadCovers();
}

function updateGroupHeader(block, groupKey) {
  if (!block) return;
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
      ? `<button class="primary" data-app-update>更新到 v${item.latest || ''}</button>` : '';
    node.innerHTML = `
      <div>
        <div>${item.display || key}</div>
        <div class="meta hint">${(item.source || '')}${item.install_dir ? ' · ' + item.install_dir : ''}</div>
      </div>
      <div class="dep-right">
        <div class="${statusClass}">${status}</div>
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
  $('cfg-staging_mods_dir').value = config.staging_mods_dir || '';
  $('cfg-runtime_dir').value = config.runtime_dir || '';
  $('cfg-xxmi_launcher').value = config.xxmi_launcher || '';
  $('cfg-migoto_loader').value = config.migoto_loader || '';
  $('cfg-official_launcher').value = config.official_launcher || '';
  $('cfg-game_exe').value = config.game_exe || '';
  $('cfg-reshade_dll').value = config.reshade_dll || '';
  if ($('cfg-dlss5_dir')) $('cfg-dlss5_dir').value = config.dlss5_dir || '';
  if ($('cfg-secondary_motion_dir')) $('cfg-secondary_motion_dir').value = config.secondary_motion_dir || '';
  $('cfg-reshade_injection').value = config.reshade_injection || 'xxmi_extra';
  $('cfg-theme').value = config.theme === 'light' ? 'light' : 'dark';
  applyTheme(config.theme === 'light' ? 'light' : 'dark');
  $('cfg-dependency_manifest').value = config.dependency_manifest || '';
  $('cfg-use_builtin_runtime').checked = config.use_builtin_runtime !== false;
  $('cfg-auto_update_dependencies').checked = !!config.auto_update_dependencies;
  $('cfg-require_admin').checked = !!config.require_admin;
  if ($('cfg-download_boost')) $('cfg-download_boost').value = config.download_boost || 'auto';
  if ($('cfg-download_line')) $('cfg-download_line').value = config.download_line || 'auto';
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
    reshade_injection: $('cfg-reshade_injection').value,
    theme: $('cfg-theme').value,
    dependency_manifest: $('cfg-dependency_manifest').value.trim(),
    use_builtin_runtime: $('cfg-use_builtin_runtime').checked,
    auto_update_dependencies: $('cfg-auto_update_dependencies').checked,
    require_admin: $('cfg-require_admin').checked,
    download_boost: $('cfg-download_boost') ? $('cfg-download_boost').value : 'auto',
    download_line: $('cfg-download_line') ? $('cfg-download_line').value : 'auto',
  };
  await call('save_config', data);
  await refreshFromState();
  $('settings-status').textContent = '设置已保存';
}

async function refreshFromState() {
  const s = await call('get_state');
  state.config = s.config;
  await refreshPaths(s.config);
  const injectUi = s.config.inject_reshade_ui !== false;
  if ($('cfg-inject-reshade-ui')) {
    $('cfg-inject-reshade-ui').checked = injectUi;
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
    $('dep-progress').max = 100;
    $('dep-progress').value = Math.max(0, Math.min(100, percent));
    // 进度条旁**只显示总进度**（百分比 + 第几个组件）；带字节的细节交给下面的日志框，
    // 否则这里会变成「0/3 XX: 12.3/27.9 MB」——两个不同量纲的进度挤在一起，看着像对不上。
    $('dep-progress-text').textContent = total
      ? `${percent.toFixed(0)}%  ·  组件 ${current}/${total}`
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
      out.textContent = JSON.stringify(progress.results || [], null, 2);
      setStatus('依赖任务完成');
      try {
        await refreshFromState();
      } catch (err) {
        /* 刷新失败不影响任务结果展示 */
      }
      break;
    }
    await new Promise(resolve => setTimeout(resolve, 400));
  }
}

let logTimer = null;

async function refreshLog() {
  const result = await call('read_launch_log', 500);
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
    if ($('log-modal').classList.contains('hidden')) openLog();
    const box = $('log-text');
    box.textContent += `

[诊断包] ${result.path}
`;
    box.scrollTop = box.scrollHeight;
    setStatus(`诊断包已导出: ${result.path}`);
  } else {
    setStatus(`导出诊断包失败: ${result.message || '未知错误'}`);
  }
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
  if (!state.config.xxmi_launcher) {
    await showAlert('还没有配置 XXMI Launcher 路径。请到设置页选择 XXMI Launcher.exe，或点击“自动检测 XXMI”。');
    showTab('settings');
    return;
  }
  if (!await showConfirm('打开官方 XXMI Launcher（EFMI 图形界面）？\n不会自动启动游戏，也不会使用自定义 Loader。')) return;
  openLog();
  setStatus('正在打开官方 XXMI Launcher...');
  const result = await call('launch_official_gui');
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
  $('prepare-btn').onclick = prepare;
  $('dep-scan-btn').onclick = async () => { await refreshFromState(); setStatus('依赖状态已刷新'); };
  $('dep-check-btn').onclick = () => startFullUpdate(true);
  $('dep-update-all-btn').onclick = () => startFullUpdate(false);
  $('prepare-launch-btn').onclick = prepare;
  $('open-log-btn').onclick = openLog;
  $('export-diagnostics-btn').onclick = exportDiagnostics;
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

  // 日志窗的 detectLogLevel / logLine / paintLog 定义在文件顶部（顶层），
  // 这里不再重复定义 —— 重复会在 bind() 作用域内遮蔽顶层版本，
  // 而 boot() 调用的是顶层那份，导致 "xxx is not defined"。

  // ── 一键启动：先跑初始化自检（缺什么补什么），再拉起 XXMI ──
  if ($('oneclick-launch-btn')) {
    $('oneclick-launch-btn').onclick = async () => {
      const btn = $('oneclick-launch-btn');
      btn.disabled = true;
      try {
        logLine('开始一键启动…');
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

        logLine('② 拉起 XXMI Launcher，请在它的界面里点 Start 启动游戏');
        const launched = await call('launch_official_gui');
        logLine(`   ${launched.message || 'XXMI Launcher 已打开'}`);
        logLine('进游戏后按 Home 打开 ReShade 面板检查插件。');
        setStatus('已拉起 XXMI，请在它的界面点 Start');
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

  // 服装 Mod 总闸：Mod 库页的「开启第三方服装 Mod」与启动页的「服装 Mod（EFMI）」是同一个开关
  async function applyModsMaster(enabled) {
    setStatus(enabled ? '正在开启第三方服装 Mod…' : '正在关闭第三方服装 Mod…');
    try {
      await call('save_config', { efmi_injection: enabled });
      await call('set_dlss5_injection', true);   // 按新状态重写注入库（去掉 / 带上 EFMI d3d11.dll）
      const st = await call('dlss5_status');
      const n = (st.extra_libraries || '').split('\n').filter((x) => x.trim()).length;
      logLine(`第三方服装 Mod: ${enabled ? '已开启' : '已关闭'}  |  XXMI 注入库 ${n} 条`);
      setStatus(enabled ? '服装 Mod 已开启' : '服装 Mod 已关闭：所有服装 Mod 不生效');
    } catch (err) {
      logLine(`✗ 服装 Mod 总闸切换失败: ${err.message || err}`);
      setStatus(`切换失败: ${err.message || err}`);
    }
    await refreshFromState();
  }
  const modsMaster = $('cfg-third-party-mods');
  if (modsMaster) modsMaster.onchange = () => applyModsMaster(modsMaster.checked);
  const efmiToggle = $('cfg-efmi-injection');
  if (efmiToggle) efmiToggle.onchange = () => applyModsMaster(efmiToggle.checked);
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

  // 右上角：版本号 + 更新检测（对比 GitHub release 的 tag）
  // 项目链接（仓库 / issue / 发布页）只在这里解析一次，界面各处共用
  const appLinks = {};

  function fillRepoLinks(repo) {
    if (!repo) return;
    const base = String(repo).replace(/\/+$/, '');
    appLinks.repo = base;
    appLinks.issues = `${base}/issues/new/choose`;
    appLinks.releases = `${base}/releases`;
    const pairs = [
      ['about-repo-link', appLinks.repo],
      ['about-issues-link', appLinks.issues],
      ['about-releases-link', appLinks.releases],
      ['crash-issue-link', appLinks.issues],
    ];
    for (const [id, url] of pairs) {
      const el = $(id);
      if (el) { el.href = url; el.textContent = url; }
    }
  }

  document.querySelectorAll('[data-open-url]').forEach((el) => {
    el.onclick = () => {
      const url = appLinks[el.dataset.openUrl];
      if (url) call('open_external', url).catch(() => {});
    };
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
    if (!await showConfirm(`发现新版本 v${r.latest}（当前 v${r.current}）\n\n现在下载并自动更新吗？\n· 更新时程序会自动退出并重启为新版\n· 更新期间请不要手动打开程序（替换过程中会被打断）\n· config.json 与 Mod 库不受影响\n· 失败会自动回滚旧版本\n\n进度会显示在「依赖」页`)) return r;

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
        if (!await showConfirm('将自动安装/更新所有组件：\n\n· 随包资产展开（DLSS 运行库、DLSS5 组件包）\n· XXMI Launcher / XXMI 库 / EFMI\n· ReShade 底座、DLSS5-Feeder、iMMERSE shader\n· 乳摇插件\n\n需要联网，继续？')) return;
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
function splashDone() {
  const el = $('splash');
  if (el) el.classList.add('hidden');
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
  splashMsg('正在绑定界面…');
  try { bind(); diag.push('bind ✓'); } catch (err) { diag.push(`bind ✗ ${err.message || err}`); console.error('bind 失败', err); }
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
  startCrashPolling();
  // 角色识别不确定的 Mod：弹窗让用户选（延后一点，别和启动流程抢时间）
  setTimeout(() => { startCharacterCheck(); }, 1500);
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
  $('crash-dir').textContent = bundle.dir || '(无)';
  $('crash-zip').textContent = bundle.zip || '(未打包成功，请直接压缩上面的文件夹)';
  const lines = [
    `时间      : ${bundle.created_at || '-'}`,
    `崩溃判定  : ${bundle.crashed ? 'CrashSight 记录到异常' : '未检测到崩溃记录（可能是正常退出）'}`,
    `收进包的终末地日志 (${(bundle.game_logs || []).length} 份):`,
    ...(bundle.game_logs || []).slice(0, 12).map((n) => `   ${n}`),
    '',
    '反馈建议：把 zip 里的内容贴到 GitHub issue，或直接发给作者。',
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
    const first = (item.candidates || [])[0] || '';
    const all = [...new Set([...(item.candidates || []), ...(data.known || [])])];
    const opts = all
      .map((n) => `<option value="${n}"${n === first ? ' selected' : ''}>${n}</option>`)
      .join('');
    row.innerHTML = `
      <div style="font-weight:600">${item.name}</div>
      <div class="hint" style="margin:2px 0 6px">${why}</div>
      <select data-char-select="${item.id}" style="min-width:220px">
        <option value="">（请选择角色）</option>
        ${opts}
      </select>
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
