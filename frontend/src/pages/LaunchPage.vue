<script setup>
// 启动页（旧 #tab-launch）：一键启动 + 六个注入开关（**与设置页共享同一份 settings 状态**）。
import { ref } from "vue";
import { call } from "../lib/bridge.js";
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

async function oneClick() {
  running.value = true;
  try {
    const result = await call("launch");
    // launch 的返回就是 launcher.launch(...) 的字典（没有统一的 message 字段），
    // 所以这里如实把结果打印出来；渲染 API 从 state 里取。
    consoleLog.value = "已发起启动。\n" + JSON.stringify(result, null, 2).slice(0, 1200);
    renderApi.value = store.state.render_api || "";
  } catch (e) {
    consoleLog.value = "启动失败：" + (e && e.message ? e.message : String(e));
  } finally {
    running.value = false;
  }
}
async function run(method, ...args) { try { return await call(method, ...args); } catch (e) { return null; } }
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
      <div class="log-box" style="max-height: 260px; border-radius: 0">{{ consoleLog }}</div>
    </div>
  </div>
</template>
