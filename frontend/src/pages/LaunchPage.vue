<script setup>
// 启动页（旧 #tab-launch）：一键启动 + 六个注入开关（**与设置页共享同一份 settings 状态**）。
import { ref } from "vue";
import { call } from "../lib/bridge.js";
import { settings, saveSetting } from "../lib/settings.js";
import { store } from "../store.js";
import Card from "../components/ui/Card.vue";
import Btn from "../components/ui/Btn.vue";
import Switch from "../components/ui/Switch.vue";

const consoleLog = ref("就绪。点「一键启动」：先跑初始化自检（缺什么补什么），再拉起 XXMI Launcher。");
const renderApi = ref("");
const running = ref(false);

const SWITCHES = [
  { k: "dlss5_addon", name: "DLSS5 神经渲染", desc: "把游戏自身的 DLSS 输出替换成 DLSS5 神经渲染" },
  { k: "firstperson_addon", name: "第一人称视角", desc: "进游戏按 F1 切换第一人称" },
  { k: "efmi_injection", name: "皮肤 Mod", desc: "EFMI 服装 Mod 注入（关掉后不加载任何皮肤）" },
  { k: "secondary_motion_injection", name: "ShakingBreastManager", desc: "乳摇物理效果" },
  { k: "poser_injection", name: "Endfield Poser", desc: "摆姿 / MMD 播放" },
  { k: "unified-hotkeys", name: "Mod 快捷键锁定", desc: "把 Mod 自带快捷键锁成内部键，避免 Mod 之间抢键" },
];

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
    <button class="w-full py-4 rounded-lg text-white text-base font-semibold transition-colors"
            :disabled="running"
            :style="{ background: running ? 'var(--border-strong)' : 'var(--accent)' }"
            @click="oneClick">
      {{ running ? "正在启动…" : "一键启动" }}
    </button>

    <Card title="注入开关">
      <div class="divide-y" style="border-color: var(--border)">
        <div v-for="s in SWITCHES" :key="s.k" class="py-3 flex items-center justify-between gap-4">
          <div class="min-w-0">
            <div class="font-medium">{{ s.name }}</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">{{ s.desc }}</div>
          </div>
          <Switch :model-value="!!settings[s.k]" @update:model-value="(v) => saveSetting(s.k, v)" />
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

    <div class="log-box h-56">{{ consoleLog }}</div>
  </div>
</template>
