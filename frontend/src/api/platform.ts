/**
 * 跨端运行环境与地址解析（见 `docs/10`）。
 *
 * App 成品端与 H5 调试端有两条硬差异，都在这里收口，别处不要自己判断：
 *
 * 1. **App 没有代理**。H5 靠 `vite.config.ts` 的代理把 `/api` 转给后端，所以相对路径能用；
 *    App 端没有代理，相对路径会打到 WebView 自己的基址（`file:///android_asset/...`），
 *    请求根本到不了后端。→ **所有网络地址一律走 `apiUrl()` / `wsUrl()` 拼成绝对地址。**
 * 2. **App 的 WebView 里 `window` 与 `EventSource` 都存在**。uni-app 的 App 是把页面跑在
 *    WebView 里的，所以"探测 `window.EventSource` 是否存在"必然误判成 H5，
 *    进而选错传输通道（该走 WebSocket 却走了 SSE）。
 *    → `isH5()` 用 uni-app **条件编译**，而不是运行时探测。
 */

/**
 * 后端基址（已经去掉末尾斜杠）。
 *
 * - **H5 调试端**：留空 → 用相对路径 → 走 `vite.config.ts` 的代理，行为与接入前完全一致；
 * - **App 成品端**：**必须**配成绝对地址，例如 `http://192.168.1.10:8000`
 *   （真机连不上 `127.0.0.1`——那是手机自己）。
 *
 * 配置方式（二选一）：
 * - 写进 `frontend/.env.local`：`VITE_API_BASE=http://192.168.1.10:8000`
 * - 构建时注入：`VITE_API_BASE=http://192.168.1.10:8000 npm run build:app`
 */
export const API_BASE = String(import.meta.env.VITE_API_BASE || '').replace(/\/+$/, '')

/**
 * 当前是否跑在 H5（浏览器）。
 *
 * 用条件编译而不是 `typeof window !== 'undefined' && window.EventSource`——
 * 后者在 App 的 WebView 里同样为真，会把 App 误判成 H5（见本文件开头第 2 条）。
 */
export function isH5(): boolean {
  let h5 = false
  // #ifdef H5
  h5 = true
  // #endif
  return h5
}

/**
 * 拼出后端绝对地址。
 *
 * App 端没配基址时**直接报错**，而不是静默拼出相对路径去打 WebView 基址——
 * 后者会表现为"请求发不出去但也不报错"，最难查。
 */
export function apiUrl(path: string): string {
  if (!API_BASE && !isH5()) {
    throw new Error('App 端未配置后端地址：请把 VITE_API_BASE 设为绝对地址（见 docs/10）')
  }
  return API_BASE + path
}

/** WebSocket 地址：App 从 API_BASE 推导；H5 调试端用同源，走 vite 代理。 */
export function wsUrl(path: string): string {
  if (API_BASE) {
    return API_BASE.replace(/^http/, 'ws') + path
  }
  const scheme = location.protocol === 'https:' ? 'wss://' : 'ws://'
  return scheme + location.host + path
}
