<script setup>
// 辅助 Mod 页（旧 #tab-assist）：只列辅助/工具类 Mod，不参与换装。
import { computed } from "vue";
import { call } from "../lib/bridge.js";
import { store } from "../store.js";
import Card from "../components/ui/Card.vue";
import { Wrench } from "lucide-vue-next";
import Btn from "../components/ui/Btn.vue";

// state 里没有独立的 assist 列表：辅助 Mod 就是 mods 里 kind === "assist" 的那些
const list = computed(() => (store.state.mods || []).filter((m) => m.kind === "assist"));
const status = "把 .zip / .7z / .rar 拖到页面任意处即可导入。";

async function rescan() { try { await call("scan"); } catch (e) { /* call 已弹窗 */ } }
async function openLib() { try { await call("open_path_in_explorer", "library"); } catch (e) {} }
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <Btn variant="primary" @click="rescan">重新扫描</Btn>
      <Btn @click="openLib">打开 Mod 库文件夹</Btn>
      <span class="text-xs" style="color: var(--text-muted)">{{ status }}</span>
    </div>
    <Card v-if="!list.length" title="辅助 Mod">
      <div class="empty-state">
        <component :is="Wrench" :size="30" class="empty-icon" />
        <div class="empty-title">这里还没有辅助 Mod</div>
        <div>辅助 Mod 是"不绑角色"的工具类 Mod（例如公共前置资源）。</div>
        <div>把 .zip / .7z / .rar 拖到窗口任意处即可导入，导入后会自动归类到这里。</div>
      </div>
    </Card>
    <!-- 标题不再写成「辅助 Mod（1）」—— 括号里那个数字没人知道是什么。
         数量挪到标题右侧的副标题位，并在卡片里说清"辅助 Mod"到底指什么。 -->
    <Card v-else title="辅助 Mod" :sub="`${list.length} 个`">
      <p class="text-xs mb-2" style="color: var(--text-muted)">
        这里放的是<b>不绑角色</b>的工具类 Mod —— 公共前置资源（例如湿润效果修复、RabbitFX
        这类别人依赖的东西）。它们不参与换装，所以不占「Mod 库」里的角色分组。
      </p>
      <div class="divide-y" style="border-color: var(--border)">
        <div v-for="m in list" :key="m.id" class="py-2.5 flex items-center justify-between gap-4">
          <div class="min-w-0">
            <div class="font-medium truncate">{{ m.name }}</div>
            <!-- 组名常常就是它自己的名字（公共前置资源没有角色归属），一样就不要重复显示 -->
            <div v-if="m.group && m.group !== m.name" class="text-xs mt-0.5" style="color: var(--text-muted)">
              {{ m.group }}
            </div>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>
