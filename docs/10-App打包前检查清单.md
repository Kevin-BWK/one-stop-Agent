# 10 App 打包前检查清单

> 状态：**H5 调试端已完成；App 端代码适配已完成（第 1/2/3/6 条）；App 仍不能打包**。
> 剩余：**依赖冲突（第 0 条）** 未解决；`appid` 待填；真机打包需 HBuilderX。
> 本文记录打包前必须处理的衔接问题（按严重程度排序），每条都给了代码位置与修法。

## 0. 依赖冲突：App 构建直接失败（当前唯一硬阻塞）

**现象**：`npm run build:app` 报
`"normalizeCssVarValue" is not exported by "@vue/shared"`。

**H5 构建不受影响**（走的解析路径不同），所以这个问题一直没暴露。

**根因**（实测版本）：

| 包 | 装到的版本 |
| --- | --- |
| `vue` | 3.5.43 |
| `@vue/runtime-core` | 3.5.43 |
| `@vue/shared` | **3.4.21** ← 落后一档 |

`package.json` 写的是 `vue: ^3.4.21` / `@vue/runtime-core: ^3.4.21`，`^` 让它们漂到了 3.5.43；
而 `@dcloudio/*` 把 `@vue/shared` 钉在 `3.4.21`。于是 `@vue/runtime-core@3.5` 要用的
`normalizeCssVarValue`（3.5 才有）在 `@vue/shared@3.4` 里找不到。

**别改错方向**：曾试过把 `vue` / `@vue/runtime-core` 降到 `3.4.21` 去对齐，结果错误换成
`"isInSSRComponentSetup" is not exported by "vue"` —— 这版 `@dcloudio/uni-app` 是**按 vue 3.5 构建的**
（`isInSSRComponentSetup` 在 3.4.21 里不存在）。**要对齐的是 `@vue/shared`，不是 `vue`。**

**修法**（二选一）：

- **A（推荐，改动小）**：把 `@vue/shared` 顶到与 `vue` 同版本

  ```json
  "overrides": { "@vue/shared": "$vue" }
  ```

  同时把 `vue` / `@vue/runtime-core` 钉成**确切版本**（继续用 `^` 会再次漂移）。
  注意 lockfile 已把这个不匹配固化了，需删掉 `package-lock.json` 重装才解得开。
- **B（更彻底）**：把整套 `@dcloudio/*` 升到支持 vue 3.5 的版本，再统一 `vue` / `@vue/shared`。

> 这两条不是纯技术选择（A 是"覆盖 uni 声明的版本"，B 是"整体升级 uni 组件"），
> 属于**团队的依赖策略**，建议与前端负责人确认后再动。

**另一个待确认项**：`@dcloudio/uni-app-plus` **尚未安装**。修完上面的冲突后若 App 构建仍失败，
多半还差它（App 平台插件）。

## 1. `fetch` 用了相对路径，App 端必挂 ✅ 已解决

**现象**：H5 靠 vite 代理把 `/api` 转给后端（同源），所以相对路径能用；
App 端**没有代理**，相对路径会打到 WebView 自己的基址（`file:///android_asset/...`），请求到不了后端。

**已做**：

- 新增 `frontend/src/api/platform.ts`，把"后端基址"收口成 `apiUrl()` / `wsUrl()`；
- **所有**网络地址一律过 `apiUrl()`——没走这个函数的路径**不可能**存在（`uni.request` / `uni.uploadFile` / SSE / WS 都从它取地址）；
- `API_BASE` 改为构建时可配：`frontend/.env.local` 里的 `VITE_API_BASE`，或构建时注入；
- H5 调试端留空即走代理，**行为与接入前完全一致**；
- App 端没配基址时**直接报错**（"App 端未配置后端地址"），而不是静默打错地址。
  后者会表现为"请求发不出去但也不报错"，最难查。

**已验证**：不配基址时构建产物里**没有**绝对地址（走代理）；配了 `VITE_API_BASE=http://192.168.1.10:8000`
后产物里**带上了**该地址。

## 2. 后端没有 CORS ✅ 已解决

**现象**：`uni.uploadFile` 走原生（plus.net），不受 CORS 限制；
但 `fetch` 是 WebView 的原生 fetch，跨域请求需要后端返回 `Access-Control-Allow-Origin`。

**已做**：按推荐方案，把 `frontend/src/api/http.ts` 里的 `fetch` **全部换成 `uni.request`**
（App 走 plus.net 原生，不受 CORS 限制），而不是给后端加 `CORSMiddleware`。
顺带统一了各端对 JSON 响应体的差异（H5 自动解析、部分端给字符串）。

> `uni.uploadFile` / `uni.connectSocket` 本来就走原生，无需改动。

## 3. `isH5()` 在 App 端误判，走错传输通道 ✅ 已解决

**现象**：App 是把页面跑在 WebView 里的，`window` 与 `EventSource` **都存在**，
于是原来的 `isH5()` 返回 `true` → 用 SSE 而不是 WebSocket，与 `docs/07` 定的方案不符。

**已做**：`isH5()` 改用 uni-app **条件编译**（`// #ifdef H5`），不再靠 `window` / `EventSource` 探测。

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

## 6. App 打包配置是空的 ✅ 部分解决

**已做**（`frontend/src/manifest.json`）：补上权限声明

- Android：`INTERNET`、`ACCESS_NETWORK_STATE`、`CAMERA`、`READ_EXTERNAL_STORAGE`、`WRITE_EXTERNAL_STORAGE`；
- iOS：`NSCameraUsageDescription`（拍摄办事材料）、`NSPhotoLibraryUsageDescription`（从相册选择）。

**仍待办**：

- **填 `appid`**（DCloud 应用标识）—— 目前是空串，需要你提供；
- Android 9+ **默认禁止明文 HTTP**：推荐上 HTTPS；若必须明文，需在打包时配 `networkSecurityConfig`；
- 真机首次跑通后，建议再核一遍最终 APK 的权限清单（Android 13+ 对相册的权限模型有变化）；
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
| **第一次真机跑 App** | **0（依赖冲突）**、填 `appid`、明文 HTTP 策略 | 半天以内（第 1/2/3/6 条已完成） |
| **给多个真实用户用** | 4、5 | 大改（Redis + 数据库 + 鉴权） |
