// 拖放导入 Mod：**照抄旧 web/app.js 的实现**（分块上传是关键 —— 一次性把整包 base64
// 丢给 pywebview 会先卡住再闪退，2026-10-01 实测过）。
import { call } from "./bridge.js";
import { showAlert, showModalDialog } from "./dialog.js";
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

export async function importDroppedFile(file, { onDone } = {}) {
  if (!file) return;
  if (!/\.(zip|7z|rar)$/i.test(file.name)) {
    await showAlert("导入 Mod", "目前只支持 .zip / .7z / .rar 压缩包（其他格式请先解压再拖进来）。");
    return;
  }
  try {
    const begin = await call("import_mod_begin", file.name);
    if (!begin || !begin.ok) {
      await showAlert("导入 Mod", (begin && begin.message) || "导入失败");
      return;
    }
    let sent = 0;
    while (sent < file.size) {
      const end = Math.min(sent + CHUNK, file.size);
      const part = await call("import_mod_chunk", begin.token, await sliceToBase64(file, sent, end));
      if (!part || !part.ok) {
        await showAlert("导入 Mod", (part && part.message) || "传输失败");
        return;
      }
      sent = end;
      setStatus(`正在上传 ${file.name}：${Math.floor((sent * 100) / Math.max(file.size, 1))}%（${(sent / 1048576).toFixed(1)} MB）`);
    }
    setStatus(`正在解压并识别角色：${file.name} …`);
    const result = await call("import_mod_finish", begin.token);
    if (!result || !result.ok) {
      await showAlert("导入 Mod", (result && result.message) || "导入失败");
      return;
    }
    if (onDone) await onDone(result);
    if (result.need_confirm && result.mod_id) {
      // 识别不出角色就直接把确认窗弹出来（旧版用户反馈过"拖进去不弹窗"）
      await showModalDialog({
        title: "这个 Mod 归到哪个角色？",
        message: `已导入「${result.name}」，但没看出属于哪个角色。\n你可以稍后在 Mod 库页点它的「⋯ → 更换归属」来设定。`,
        okText: "知道了", showCancel: false,
      });
    } else if (result.group) {
      await showAlert("导入 Mod", `已导入「${result.name}」，识别为「${result.group}」。`);
    } else {
      await showAlert("导入 Mod", result.warning || `已导入「${result.name}」。`);
    }
  } catch (err) {
    await showAlert("导入 Mod", `导入失败：${(err && err.message) || err}`);
  }
}
