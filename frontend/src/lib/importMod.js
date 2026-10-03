// 拖放导入 Mod：**照抄旧 web/app.js 的实现**（分块上传是关键 —— 一次性把整包 base64
// 丢给 pywebview 会先卡住再闪退，2026-10-01 实测过）。
import { call } from "./bridge.js";
import { showAlert, showModalDialog, showProgressToast, hideProgressToast } from "./dialog.js";
import { setStatus } from "./status.js";

const CHUNK = 1024 * 1024;

export function dragHasFiles(event) {
  const types = event.dataTransfer && event.dataTransfer.types;
  return !!types && Array.prototype.indexOf.call(types, "Files") >= 0;
}

// 分块调用：单块 1 MB，用 FileReader 转 base64（别用 String.fromCharCode(...big) —— 会爆栈）
function sliceToBase64(file, start, end) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("读取失败"));
    reader.onload = () => {
      const text = String(reader.result || "");
      resolve(text.slice(text.indexOf(",") + 1));
    };
    reader.readAsDataURL(file.slice(start, end));
  });
}

export async function importDroppedFile(file, { onDone, onNeedConfirm } = {}) {
  if (!file) return;
  if (!/\.(zip|7z|rar)$/i.test(file.name)) {
    await showAlert("导入 Mod", "目前只支持 .zip / .7z / .rar 压缩包（其他格式请先解压再拖进来）。");
    return;
  }
  try {
    showProgressToast("import", `准备导入 ${file.name} …`);
    const begin = await call("import_mod_begin", file.name);
    if (!begin || !begin.ok) {
      hideProgressToast("import");       // 失败也要撤掉进度，否则界面停在"准备导入…"
      await showAlert("导入 Mod", (begin && begin.message) || "导入失败");
      return;
    }
    let sent = 0;
    while (sent < file.size) {
      const end = Math.min(sent + CHUNK, file.size);
      const part = await call("import_mod_chunk", begin.token, await sliceToBase64(file, sent, end));
      if (!part || !part.ok) {
        // ⚠️⚠️ **"卡在那里不动"的一半在这里**（2026-10-03 用户：「mod 超过 600mb 就显示
        // 请手动解压放入，**但是动态还一直卡在那里**」）。
        // 后端超限时只回了一句错误，前端虽然 `return` 了，但**那条自我更新的进度提示
        // 没有撤掉**（`hideProgressToast("import")` 只在成功路径上调）⇒ 进度条永远停在
        // 超限那一刻，看起来就是"卡死"。现在：**任何失败分支都先把进度提示撤掉**。
        hideProgressToast("import");
        await showAlert("导入 Mod", (part && part.message) || "传输失败");
        return;
      }
      sent = end;
      // 用**一条会自我更新**的进度提示：原来这里是 setStatus，而 setStatus 带 toast，
      // 于是每 1MB 弹一条、大包连弹上百条（用户反馈的"弹出来一堆动态"）。
      const pct = Math.floor((sent * 100) / Math.max(file.size, 1));
      showProgressToast("import", `正在上传 ${file.name}：${pct}%（${(sent / 1048576).toFixed(1)} MB）`);
      setStatus(`正在上传 ${file.name}：${pct}%`);
    }
    showProgressToast("import", `正在解压并识别角色：${file.name} …`);
    setStatus(`正在解压并识别角色：${file.name} …`);
    const result = await call("import_mod_finish", begin.token);
    if (!result || !result.ok) {
      hideProgressToast("import");       // 失败也要撤掉进度，否则停在"正在解压…"
      await showAlert("导入 Mod", (result && result.message) || "导入失败");
      return;
    }
    hideProgressToast("import");   // 收尾：把进度提示撤掉
    if (onDone) await onDone(result);
    if (result.need_confirm && result.mod_id) {
      // ⚠️⚠️ **B12：识别不出角色时直接推角色选择窗**（2026-10-03 补回归）。
      // 0.9.5（`app.js:1085-1090`）：`result.need_confirm` ⇒ `startCharacterCheck(mod_id)`
      // **直接把选择窗推给用户**，当场就能归好类。
      // 换代后这里只弹一句"你可以稍后点 ⋯→更换归属" —— 把一步能做完的事推给了用户，
      // 而用户 2026-10-03 反馈过「拖进去不弹窗」正是这类问题的变体。
      // 这里回调给调用方（页面）去开 `CharacterPickerDialog`；拿不到回调才退回提示框。
      if (onNeedConfirm) {
        await onNeedConfirm(result);
      } else {
        await showModalDialog({
          title: "这个 Mod 归到哪个角色？",
          message: `已导入「${result.name}」，但没看出属于哪个角色。\n\n` +
            "去 Mod 库页点它的「⋯ → 更换归属」就能设定。",
          okText: "知道了", showCancel: false,
        });
      }
    } else if (result.group) {
      await showAlert("导入 Mod", `已导入「${result.name}」，识别为「${result.group}」。`);
    } else {
      await showAlert("导入 Mod", result.warning || `已导入「${result.name}」。`);
    }
  } catch (err) {
    // ⚠️ **任何异常都要撤掉进度提示** —— 这是"动态一直卡在那里"的最后一道兜底：
    // 进度 toast 是 sticky 的（同一 key 只占一条、不会自己消失），不主动撤就会一直挂着。
    hideProgressToast("import");
    await showAlert("导入 Mod", `导入失败：${(err && err.message) || err}`);
  }
}
