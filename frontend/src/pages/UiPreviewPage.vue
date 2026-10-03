<script setup>
// UI 预览页（`index.html#preview?d=alert|confirm|modal|conflict|menu|drop|toast`）
// 用途：把**真实弹窗组件**按真实样式渲染出来，便于截图送评审 / 回归对比。
// 正常使用不会进到这里（只有显式带 #preview 才显示），也不调用任何后端。
import { ref, onMounted } from "vue";
import ConflictDialog from "../components/ConflictDialog.vue";
import { CheckCircle2, AlertTriangle, XCircle, Info } from "lucide-vue-next";

const ICONS = { success: CheckCircle2, warn: AlertTriangle, danger: XCircle, info: Info };
const COLORS = { success: "var(--success)", warn: "var(--warn)", danger: "var(--danger)", info: "var(--accent)" };

const which = ref("alert");
const demo = ref(false);
const toastKind = ref("info");

onMounted(() => {
  const q = String(location.hash || "").split("?")[1] || "";
  const d = new URLSearchParams(q).get("d");
  if (d) which.value = d;
});

const CONFLICT_GROUPS = [
  { group: "head", reason: "都替换了头部网格", mods: [
    { id: "a1", name: "莱万汀 as 2B Nier（PrimoStudios）" },
    { id: "a2", name: "莱万汀 尘白禁区 风格包" },
  ] },
  { group: "body", reason: "都替换了同一套身体贴图", mods: [
    { id: "b1", name: "佩丽卡 OL 装" },
    { id: "b2", name: "佩丽卡 点墨化龙" },
    { id: "b3", name: "佩丽卡 泳装" },
  ] },
  { group: "weapon", reason: "共享同一份武器模型", mods: [
    { id: "c1", name: "陈千语 太刀替换" },
    { id: "c2", name: "陈千语 长剑替换" },
  ] },
];
const MENU = ["更换归属…", "修复", "回滚", "打开所在目录"];
</script>

<template>
  <div class="space-y-4">
    <div class="text-xs" style="color: var(--text-muted)">
      预览：<b>{{ which }}</b> —— 这是一张真实组件的渲染图（不带后端）。
    </div>

    <!-- ① 提示框 -->
    <div v-if="which === 'alert'" class="card">
      <div class="card-head">提示</div>
      <div class="card-body">
        <p style="white-space: pre-wrap">已导入「莱万汀 as 2B Nier」，识别为「莱万汀」。</p>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <button class="btn btn-primary">知道了</button>
      </div>
    </div>

    <!-- ② 确认框（危险动作：主选项在右、文字自解释） -->
    <div v-if="which === 'confirm'" class="card">
      <div class="card-head">确认</div>
      <div class="card-body">
        <p style="white-space: pre-wrap">把这个 Mod 移出库？

它会被移到 runtime\backups\mod-trash\（可找回），原库不再显示。</p>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <button class="btn btn-secondary">算了</button>
        <button class="btn btn-primary">移出库</button>
      </div>
    </div>

    <!-- ③ 多行说明弹窗（首启引导的样式） -->
    <div v-if="which === 'modal'" class="card">
      <div class="card-head">第一次使用：还没完成初始化</div>
      <div class="card-body">
        <p style="white-space: pre-wrap">当前缺少：Poser。

接下来可以做两件事（约 1 分钟）：
· 在「依赖」页点「自动安装/更新」把组件装齐；
· 在「Mod 库」页把 .zip / .7z / .rar 拖进来导入 Mod。

⚠️ 第一次点「一键启动」如果终末地没起来，再点一次通常就好。</p>
      </div>
      <div class="px-4 py-3 flex justify-end gap-2 border-t" style="border-color: var(--border)">
        <button class="btn btn-secondary">跳过</button>
        <button class="btn btn-primary">去依赖页</button>
      </div>
    </div>

    <!-- ④ 冲突处理（每组一个下拉框） -->
    <div v-if="which === 'conflict'">
      <ConflictDialog :groups="CONFLICT_GROUPS" @resolve="() => {}" @cancel="() => {}" />
    </div>

    <!-- ⑤ Mod 卡片 ⋯ 菜单（就地小菜单） -->
    <div v-if="which === 'menu'" class="card">
      <div class="card-head">Mod 卡片上的「⋯」</div>
      <div class="card-body">
        <div class="flex items-start justify-between gap-2 rounded-lg border p-2.5" style="border-color: var(--border); max-width: 260px">
          <div class="min-w-0">
            <div class="font-medium truncate text-sm">莱万汀 as 2B Nier</div>
            <div class="text-xs mt-0.5" style="color: var(--text-muted)">已勾选</div>
          </div>
          <button class="btn btn-mini shrink-0">⋯</button>
        </div>
        <div class="card py-1 shadow-lg mt-2" style="min-width: 172px">
          <button v-for="m in MENU" :key="m" class="w-full text-left px-3 py-1.5 text-sm">{{ m }}</button>
          <div style="height:1px;background:var(--border)" class="my-1"></div>
          <button class="w-full text-left px-3 py-1.5 text-sm" style="color: var(--danger)">移出 Mod 库</button>
        </div>
      </div>
    </div>

    <!-- ⑥ 拖放提示层 -->
    <div v-if="which === 'drop'" class="rounded-lg" style="background: rgba(0,0,0,.35); padding: 80px 0">
      <div class="card px-6 py-4 text-center shadow-lg" style="max-width: 340px; margin: 0 auto">
        <div class="font-medium">松手即可导入 Mod</div>
        <div class="text-xs mt-1" style="color: var(--text-muted)">支持 .zip / .7z / .rar（进度显示在顶部提示条）</div>
      </div>
    </div>

    <!-- ⑦ Toast 三种 -->
    <div v-if="which === 'toast'" class="space-y-3" style="max-width: 420px">
      <div v-for="t in [
        { tone: 'success', text: '已修复「莱万汀 as 2B Nier」' },
        { tone: 'warn', text: '「佩丽卡 OL 装」的角色归属不确定，可在它的「⋯」里更改所属角色' },
        { tone: 'danger', text: '导入失败：压缩包已损坏，请换一个文件重试' },
        { tone: 'info', text: '已开始 3 个下载任务（并行）' },
      ]" :key="t.tone"
           class="px-3.5 py-2.5 rounded-lg text-sm shadow-md flex items-start gap-2"
           style="background: var(--surface); border: 1px solid var(--border)">
        <component :is="ICONS[t.tone]" :size="15" class="shrink-0" :style="{ color: COLORS[t.tone], marginTop: '2px' }" />
        <span>{{ t.text }}</span>
      </div>
    </div>
  </div>
</template>
