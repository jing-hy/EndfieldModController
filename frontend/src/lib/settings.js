// 集中管理所有设置项（启动页与设置页用的是**同一批注入开关**，旧版靠手工双向同步，
// 这里天然共享同一份 reactive 状态）。
//
// ⚠️ 保存语义必须与旧版一致：`save_config` **只发改动的那一个键**
//    （旧代码：`{last_tab: target}` / `{selected_mods: ids}`）。
//    发全量会把别的页面/别的时机刚改好的值覆盖回去。
import { reactive } from "vue";
import { call } from "./bridge.js";
import { store } from "../store.js";

export const settings = reactive({});
export const settingsReady = reactive({ value: false });

export function loadSettings() {
  const cfg = (store.state && store.state.config) || {};
  for (const key of Object.keys(settings)) delete settings[key];
  Object.assign(settings, cfg);
  settingsReady.value = true;
}

export async function saveSetting(key, value) {
  settings[key] = value;
  try {
    const result = await call("save_config", { [key]: value });
    // save_config 会把"留空 = 自动"回填后的值返回，这里同步回来（用户能看到自动推导结果）
    let applied = value;
    if (result && typeof result === "object") {
      if (key in result) {
        applied = result[key];
      } else if (result.config && typeof result.config === "object" && key in result.config) {
        applied = result.config[key];      // 实际返回的是 {ok, config:{...}}
      }
    }
    settings[key] = applied;

    // ★ 必须同步回 store.state.config —— `loadSettings()` 是"从 store.state.config
    //   整份重灌"的，如果这里不同步，**下一次任何 refreshState()+loadSettings()
    //   （切页、改别的设置、刷状态都会触发）就会拿旧值把你刚改的覆盖回去**。
    //   用户看到的现象就是「关了开关马上又自己打开」（2026-10-03 反馈）。
    if (store.state) {
      if (!store.state.config || typeof store.state.config !== "object") store.state.config = {};
      store.state.config[key] = applied;
    }
    return result;
  } catch (e) {
    return null;   // call() 已经弹过窗，调用方不必再处理
  }
}
