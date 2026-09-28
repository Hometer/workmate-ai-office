// API 封装：统一 fetch、错误归一化。
export async function apiGet(path) {
  const r = await fetch(path);
  return handle(r);
}

export async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handle(r);
}

export async function apiUpload(path, file) {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch(path, { method: "POST", body: form });
  return handle(r);
}

async function handle(r) {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = (data.error && data.error.message) || `请求失败（${r.status}）`;
    throw new Error(msg);
  }
  return data;
}
