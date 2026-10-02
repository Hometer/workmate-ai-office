// API 封装：统一 fetch、错误归一化。
/** @param {string} path */
export async function apiGet(path) {
  const r = await request(path);
  return handle(r);
}

/** @param {string} path @param {unknown} body */
export async function apiPost(path, body) {
  const r = await request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, 30000);
  return handle(r);
}

/** @param {string} path @param {File} file */
export async function apiUpload(path, file) {
  const form = new FormData();
  form.append("file", file);
  const r = await request(path, { method: "POST", body: form }, 60000);
  return handle(r);
}

/** @param {string} path @param {RequestInit} [options] */
async function request(path, options = {}, timeout = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(path, { ...options, signal: controller.signal });
  } catch (error) {
    const timedOut = controller.signal.aborted;
    const message = timedOut ? "连接超时，请确认本地服务正常后重试。" : "无法连接本地服务，请确认 WorkMate 正在运行。";
    throw new Error(message + (path === "/api/v1/tasks" && options.method === "POST" ? "任务可能已受理，请先在历史成果中检查，避免重复生成。" : ""));
  } finally {
    clearTimeout(timer);
  }
}

/** @param {Response} r @returns {Promise<unknown>} */
async function handle(r) {
  /** @type {unknown} */
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const error = data && typeof data === "object" && "error" in data ? data.error : null;
    const msg = error && typeof error === "object" && "message" in error && typeof error.message === "string" ? error.message : `请求失败（${r.status}）`;
    throw new Error(msg);
  }
  return data;
}
