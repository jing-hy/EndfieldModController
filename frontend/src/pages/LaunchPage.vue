<script setup>
// 启动页（旧 #tab-launch）：一键启动 + 六个注入开关（**与设置页共享同一份 settings 状态**）。
import { ref, onMounted, onUnmounted } from "vue";
import { call } from "../lib/bridge.js";
import { useLogAutoScroll } from "../lib/autoscroll.js";
import { showAlert } from "../lib/dialog.js";
import { settings, saveSetting } from "../lib/settings.js";
import { store } from "../store.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Switch from "../components/ui/Switch.vue";

const consoleLog = ref("就绪。点「一键启动」：先跑初始化自检（缺什么补什么），再拉起 XXMI Launcher。");
const renderApi = ref("");
const running = ref(false);

const SWITCHES = [
  { k: "dlss5_addon_enabled", name: "DLSS5 神经渲染", desc: "把游戏自身的 DLSS 输出替换成 DLSS5 神经渲染",
    apply: (v) => call("set_component_addon", "dlss5", v) },
  { k: "firstperson_addon_enabled", name: "第一人称视角", desc: "进游戏按 F1 切换第一人称",
    apply: (v) => call("set_component_addon", "firstperson", v) },
  { k: "efmi_injection", name: "皮肤 Mod", desc: "EFMI 服装 Mod 注入（关掉后不加载任何皮肤）" },
  { k: "secondary_motion_injection", name: "ShakingBreastManager", desc: "乳摇物理效果" },
  { k: "poser_injection", name: "Endfield Poser", desc: "摆姿 / MMD 播放",
    apply: (v) => call("set_poser_enabled", v) },
  { k: "hotkey_takeover", name: "Mod 快捷键锁定", desc: "把 Mod 自带快捷键锁成内部键，避免 Mod 之间抢键",
    apply: (v) => call("set_hotkey_takeover", v) },
];

// 切换一个开关：有专用接口的走专用接口（它们还要动文件/注入库），其余只写配置。
async function toggleSwitch(sw) {
  const next = !settings[sw.k];
  settings[sw.k] = next;                       // 先动界面，避免点了没反应
  try {
    if (sw.apply) {
      const r = await sw.apply(next);
      if (r && r.ok === false) {
        settings[sw.k] = !next;                // 后端拒绝（例如非 50 系开 DLSS5）→ 回滚
        await showAlert("没能改这个开关", r.message || "未知原因");
        return;
      }
    } else {
      await saveSetting(sw.k, next);
    }
    await refreshState();
    loadSettings();
  } catch (e) { /* call() 已经弹过窗 */ }
}

// 启动页日志 = **真实启动日志**（`runtime\logs\launch.log`，后端 `read_launch_log`）。
// 用户 2026-10-03：「现在日志展示的是 json，不是启动过程」—— 那次是我把 launch() 的
// 返回值 JSON.stringify 出来顶掉了日志。这里恢复成"跟日志"：
// 启动后立刻拉一次，然后 1.5 秒轮询一次，跟着看到「注入自检 / 拉起 XXMI / 进程监视」全过程。
let logTimer = null;
async function pullLaunchLog() {
  try {
    // 后端 `read_launch_log(tail)` 返回的是 `{ok, text}`（整段文本，不是数组）——
    // 一开始我按 `lines`/`log` 猜字段，结果拿不到内容。
    const r = await call("read_launch_log", 200);
    const text = (r && r.text) || "";
    if (!String(text).trim()) return;
    consoleLog.value = String(text)
      .split(/\r?\n/)
      .filter((ln) => ln.trim())
      .join("\n");
  } catch (e) { /* 读不到就保持原样 */ }
}
function startLogPolling() {
  if (logTimer) return;
  logTimer = setInterval(pullLaunchLog, 1500);
  // 一分钟足够覆盖"注入 → 拉起 XXMI → 进程监视"这段；之后停掉，不常驻
  setTimeout(() => { if (logTimer) { clearInterval(logTimer); logTimer = null; } }, 60000);
}
onUnmounted(() => { if (logTimer) clearInterval(logTimer); });

async function oneClick() {
  // ⚠️ **先检查运行环境是否齐备，缺就拒绝启动**（用户 2026-10-03 明确要求：
  // 「不存在应该拒绝启动弹出弹窗，然后跳转依赖开始下载」）。
  //
  // 背景：XXMI 本体缺失时，原来的流程会一头扎进 `ensure_xxmi()` 去联网下载 ——
  // 而下载是后台线程、`byte_progress` 按设计**只更新百分比不写日志**，直连被掐的网络下
  // 连接阶段会一直等（实测卡了十几分钟，日志停在 `builtin XXMI: checking`），
  // 界面上看起来就是"拉不起 XXMI"、也没有任何原因。这种"静默卡死"最难排查。
  try {
    const st = await call("get_state");
    const report = (st && st.dependency_report && st.dependency_report.manifest) || {};
    const missing = Object.entries(report)
      .filter(([, v]) => v && v.required !== false && v.present === false)
      .map(([key, v]) => ({ key, name: v.display || key }));
    if (missing.length) {
      const names = missing.map((m) => `· ${m.name}`).join("\n");
      const go = await showModalDialog({
        title: "运行环境还没装好，先不启动",
        message:
          `缺这些组件：\n${names}\n\n` +
          "现在启动会直接失败（或者卡在下载上）。建议先去「依赖」页把它们装好 —— " +
          "点下面的「去安装」会跳过去并自动开始下载。",
        okText: "去安装", cancelText: "取消",
      });
      if (go) {
        store.autoStartDeps = true;
        store.tab = "dependencies";
      }
      consoleLog.value = "缺少组件，已拦下启动：\n" + names;
      return;
    }
  } catch (e) { /* 查不到就按原样往下走，别因为检查本身挡住用户 */ }

  running.value = true;
  try {
    await call("launch");
    renderApi.value = store.state.render_api || "";
    // ⚠️ **不要打印 launch() 的返回值**（2026-10-03 用户反馈：「现在日志展示的是 json，
    // 不是启动过程」）—— 我一度把那坨字典 `JSON.stringify` 出来，结果启动页日志窗
    // 全是 JSON，看不到真正的启动过程。
    // 启动页要的是**日志本身**：后端 `read_launch_log()` 读的就是 `runtime\logs\launch.log`
    //（与依赖页那个日志框同源）。先立刻拉一次，再开轮询持续跟。
    await pullLaunchLog();
    startLogPolling();
  } catch (e) {
    consoleLog.value = (consoleLog.value || "") + "\n启动失败：" + (e && e.message ? e.message : String(e));
  } finally {
    running.value = false;
  }
}
// ⚠️⚠️ **同 SettingsPage：`run()` 不能静默**（2026-10-03 统一修）。
// 原来 `catch { return null }` 把异常吞掉、也不看返回值 ⇒ 本页多个按钮"点了没反应"
//（「启动插件界面」「打开摆姿页」「生成控制器」「检查/修复完整性」…）。
async function run(method, ...args) {
  try {
    const result = await call(method, ...args);
    if (result && result.ok === false) {
      await showAlert("操作未完成", String(result.message || result.reason || "未知原因"));
    }
    return result;
  } catch (e) {
    await showAlert("操作失败", String((e && e.message) || e || "未知原因"));
    return null;
  }
}

// 日志框自动滚到底（不抢鼠标、没新内容不动）
const logBox = ref(null);
useLogAutoScroll(logBox, () => consoleLog.value);
</script>

<template>
  <div class="space-y-4">
    <button id="oneclick-launch-btn"
            class="w-full py-4 rounded-lg text-white text-base font-semibold transition-colors"
            :disabled="running"
            :style="{ background: running ? 'var(--border-strong)' : 'var(--accent)' }"
            @click="oneClick">
      {{ running ? "正在启动…" : "一键启动" }}
    </button>

    <Card title="注入开关">
      <div class="divide-y" style="border-color: var(--border)">
        <div v-for="sw in SWITCHES" :key="sw.k" class="switch-row" @click="toggleSwitch(sw)">
          <div class="min-w-0">
            <div class="font-medium">{{ sw.name }}</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">{{ sw.desc }}</div>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="switch-state">{{ settings[sw.k] ? "已开启" : "已关闭" }}</span>
            <Switch :model-value="!!settings[sw.k]" @update:model-value="() => toggleSwitch(sw)" />
          </div>
        </div>
      </div>
    </Card>

    <div class="flex flex-wrap gap-2">
      <Btn @click="run('launch_secondary_motion')">启动插件界面（乳摇管理器）</Btn>
      <Btn @click="run('open_poser_web_ui')">打开摆姿页（Poser）</Btn>
      <Btn @click="run('prepare_launch')">生成控制器</Btn>
      <Btn @click="run('check_integrity')">检查/修复完整性</Btn>
      <Btn @click="run('audit_game_injections')">检查游戏目录注入</Btn>
      <span v-if="renderApi" class="text-xs self-center" style="color: var(--text-muted)">{{ renderApi }}</span>
    </div>

    <div class="log-card">
      <div class="log-card-head"><span>运行日志</span></div>
      <div ref="logBox" class="log-box" style="max-height: 260px; border-radius: 0">{{ consoleLog }}</div>
    </div>
  </div>
</template>
