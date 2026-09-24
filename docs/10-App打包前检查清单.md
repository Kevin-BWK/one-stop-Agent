# 10 App 打包前检查清单

> 状态：**H5 调试端已完成，App 成品端尚未打包**。
> 本文记录打包前必须处理的衔接问题（按严重程度排序），每条都给了代码位置与修法。
> 前 4 条都是"让 App 能连上后端"，现在改成本最低。

## 1. `fetch` 用了相对路径，App 端必挂（最严重）

**现象**：H5 靠 vite 代理把 `/api` 转给后端（同源），所以相对路径能用；
App 端**没有代理**，相对路径会打到 WebView 自己的基址（`file:///android_asset/...`），请求到不了后端。

**证据**（`frontend/src/api/http.ts`）：

```ts
const API_BASE = ''                              // L7
fetch('/scenarios/' + scenarioId)                // L41  ← 没带 API_BASE
fetch('/api/cases/' + caseId)                    // L49  ← 没带
fetch('/api/ask', {...})                         // L63  ← 没带
fetch(API_BASE + '/api/materials/intake', ...)   // L81  ← 带了
```

**修法**：**所有** `fetch(` 调用统一带上 `API_BASE`（上面三处 + 之后新增的 `createSession` 等；
本节行号写于记录时，会随后续改动漂移，改的时候按 `fetch(` 全量搜一遍）；并把 `API_BASE`
改成可配置（构建时注入，或从 `manifest.json` 的 `app-plus.distribute` / extra 读取），
而不是硬编码空串。

> 注意：`uni.uploadFile` / `uni.request` 走原生，不需要 `API_BASE` 也能跨域，但**相对路径同样要不得**
> ——App 端没有代理，相对路径会打到 WebView 自己的基址。所以凡是网络调用，URL 都必须是绝对地址。

## 2. 后端没有 CORS

**现象**：`uni.uploadFile` 走原生（plus.net），不受 CORS 限制；
但 `fetch` 是 WebView 的原生 fetch，跨域请求需要后端返回 `Access-Control-Allow-Origin`。

**证据**：在 `server/` 里搜 `CORS` / `add_middleware` / `allow_origins` → **0 命中**。

**修法**（二选一）：

- 后端加 `CORSMiddleware`（简单，但要维护白名单）；
- 前端把 `fetch` 全部换成 `uni.request`（走原生，彻底绕开 CORS，也更贴合 uni-app 跨端习惯）。**推荐**。

## 3. `isH5()` 在 App 端误判，走错传输通道

**现象**：uni-app 的 App 是把页面跑在 WebView 里的，`window` 与 `EventSource` **都存在**，
于是 `isH5()` 返回 `true` → 用 SSE 而不是 WebSocket。而 `docs/07` 定的方案是"App 成品端走 WebSocket"。

**证据**（`frontend/src/api/stream.ts`）：

```ts
export function isH5(): boolean {                                    // L29
  return typeof window !== 'undefined' && typeof (window as any).EventSource !== 'undefined'
}
```

**修法**：改用 uni-app 条件编译（`// #ifdef H5` / `// #ifndef H5`），
或 `uni.getSystemInfoSync().uniPlatform === 'web'`。

## 4. 服务端是"单进程 + 内存状态"，多用户会出问题

现在是**单用户 Demo 架构**，给多个 App 用户用之前必须换掉：

| 位置 | 状态 | 后果 |
| --- | --- | --- |
| `app/mock_gov/services.py::MockGovServices._seq` | 进程内自增，**无锁** | 并发提交会重号 |
| `server/service.py::AgentService.sessions` | 进程内 dict | `uvicorn --workers 4` 时会话互相找不到 |
| `app/materials/store.py::MaterialStore._intakes` | 进程内 dict + JSON 文件 | 同上 |
| `app/storage/repo.py::JsonFileRepo` | 整文件读写 | 多进程同时写会互相覆盖 |

**修法**：会话与材料收集单进 Redis，办理单进 PostgreSQL/MySQL，单号改成数据库序列或带实例号。
README 的"桩实现 → 真实接入"表里已经许了这件事，这里是它的**硬门槛**。

## 5. 材料文件接口没有鉴权

**现象**：`server/materials.py::read_file`
（`GET /api/materials/{intake_id}/{material_id}/files/{file_id}`）
——谁知道 URL 谁就能下载身份证照片。

**修法**：上线前必须加鉴权（token / 会话校验）+ HTTPS + 访问控制。
材料属敏感个人信息，这是**合规硬要求**，不是优化项。

## 6. App 打包配置是空的

**证据**（`frontend/src/manifest.json`）：`appid` 是空串，`app-plus` 里**没有任何权限声明**。

**修法**：

- 填 `appid`（DCloud 应用标识）；
- 声明权限：相机、相册（`uni.chooseImage({sourceType:['camera','album']})` 需要）、网络；
- Android 9+ **默认禁止明文 HTTP**：要么上 HTTPS，要么配 `networkSecurityConfig`；
- 打包命令已就绪：`npm run build:app`（或 HBuilderX 云打包）。

## 已经做对、不用改的

- ✅ 上传用 `uni.uploadFile`（multipart）而非 base64 塞 JSON —— App 走原生上传器，能吃大图、不占 WebView 内存
- ✅ 拍照 / 相册用 `uni.chooseImage({sourceType:['camera','album']})`，`sizeType:['original']`
- ✅ 后端不参与打包，App 包体积不受 Python 影响
- ✅ `package.json` 已有 `dev:app` / `build:app` 脚本
- ✅ 前后端契约是 JSON + multipart，与语言无关

## 分阶段

| 阶段 | 要解决 | 工作量 |
| --- | --- | --- |
| 现在（H5 调试） | 无 | 0 |
| **第一次真机跑 App** | 1、2、3、6 | 半天（都是小改） |
| **给多个真实用户用** | 4、5 | 大改（Redis + 数据库 + 鉴权） |
