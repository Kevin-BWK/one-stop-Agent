# 10 App 打包前检查清单

> 状态：**H5 调试端已完成；App 端代码适配、依赖冲突与打包配置均已就绪，`npm run build:app` 已产出可导入 HBuilderX 的产物**。
> 剩余：`appid` 需换成 DCloud 正式值（`__UNI__` 开头，当前用项目名占位）；真机打包需 HBuilderX；第 4/5 条是多用户上线前的事。
> 本文记录打包前必须处理的衔接问题（按严重程度排序），每条都给了代码位置与修法。

## 0. 依赖冲突：App 构建直接失败 ✅ 已解决

**现象**（两个错，先后出现）：

1. `npm run build:app` 报 `"normalizeCssVarValue" is not exported by "@vue/shared"`；
2. 修掉它之后又报 `"isInSSRComponentSetup" is not exported by "vue"`。

**H5 构建与 dev server 一直看不出问题**，所以这条藏了很久。

**根因（两件事叠加）**：

1. **`@dcloudio/uni-app-plus` 没装**。App 平台插件缺失时，编译期解析不到 `isInSSRComponentSetup`
   （它来自 vue 3.5 的运行时导出）——这是第 2 个错的来源。
2. **`vue` / `@vue/runtime-core` 被 `^3.4.21` 漂到了 3.5.43**。而 uni 整套是按 **vue 3.4.21**
   构建的（`@dcloudio/*` 一律声明 `vue: 3.4.21`、`@vue/shared: 3.4.21`）。
   vue 3.5.43 的 `@vue/runtime-core` 要用 `@vue/shared@3.5.43` 的 `normalizeCssVarValue`（3.4 没有）——
   这是第 1 个错的来源。

**已做**（`frontend/package.json`，四条一起）：

- 补装 `@dcloudio/uni-app-plus@3.0.0-5020620260917001`（App 平台插件，此前缺失）；
- `vue` / `@vue/runtime-core` 从 `^3.4.21` 改成**确切版本 `3.4.21`**（回到 uni 声明的版本；
  继续用 `^` 会再次漂到 3.5）；
- `pinia` 钉成 `2.2.2`（`^2.2.6` 会解析到 2.3.1，而 2.3.x 的 peer 要求 `vue ^3.5.11`，与 3.4 冲突）；
- 删掉 `package-lock.json` 重建（旧 lockfile 已把不匹配固化，增量 install 解不开）。

**还必须有这个 override**：

```json
"overrides": { "@vue/shared": "3.4.21" }
```

原因：`@dcloudio/vite-plugin-uni` 带了一条**构建期**依赖链
`@vitejs/plugin-vue-jsx → @vue/babel-plugin-jsx → @vue/compiler-sfc@3.5.43 → @vue/shared@3.5.43`，
它会把 `@vue/shared@3.5.43` **提升到顶层**（项目其实不用 JSX）。而 **vite 的依赖优化会把
`@vue/shared` 扁平化到顶层那一份**，于是 H5 运行时（`@dcloudio/uni-h5-vue`，一份 3.4 系的 Vue）
也拿到了 3.5 的 shared，切换场景重建组件时抛：

```
TypeError: Cannot assign to read only property '_' of object
    at updateSlots → updateComponentPreRender → patchKeyedChildren
```

抛错发生在 patch 链中间，**DOM 停在半新半旧**：胶囊与表单字段还是旧场景的，
而对话区标题与必填提示已经是新场景的——看起来就像"点了没反应 / 只变了一半"。
把顶层压回 3.4.21 即可。

**已验证**（用 `frontend/scripts/probe-h5.mjs` 实测，见文末"怎么验前端"）：

- 点「开办企业」后：胶囊变 `开办企业[*]`、对话区标题变「开办企业一件事」、表单变 7 个企业字段、
  两处必填提示都变 3 项企业字段，且**控制台无 error**；
- `vue-tsc` 零错误；H5 构建成功（`dist/build/h5/`）；**App 构建成功**（`dist/build/app/`，
  日志提示 `open HBuilderX, import dist\build\app run`）；
- App 产物 `manifest.json` 里能看到第 6 条声明的全部权限；`VITE_API_BASE` 确实注入进了 `app-service.js`。

**为什么不用"升级整套 `@dcloudio`"来修**：查了更新一版的 `@dcloudio/uni-h5`（`vue3` tag，
`3.0.0-alpha-5020720260921001`，比在用版本新），它**仍然声明 `vue: 3.4.21` / `@vue/shared: 3.4.21`**
——说明 3.4.21 就是这一代 uni 的目标版本，升级不解决问题。升 uni 组件应作为独立的
工具链升级事项来做，不要和这个 bug 绑在一起。

> **排查路上踩过的两个坑（记录以免重犯）**：
>
> 1. 一度以为"要往 vue 3.5 对齐"，用 `overrides: { "@vue/shared": "$vue" }` 把 shared 顶到 3.5.43。
>    App 构建确实过了，但**把 H5 弄坏了**——就是上面那个 slots 报错。
>    **不要用 override 把 shared 顶到 3.5**，H5 运行时（`uni-h5-vue`）会挂。
> 2. 又一度以为"vue 必须 ≥3.5"（因为降到 3.4.21 时报 `isInSSRComponentSetup`），
>    其实那只是因为当时 `@dcloudio/uni-app-plus` **还没装**。装上之后，全套 3.4.21
>    能同时通过 App 构建与 H5 渲染。
>
> 结论：**以 `@dcloudio` 声明的版本为准（vue 3.4.21）**，并把构建期依赖顶上去的
> `@vue/shared` 压回同版本。

**一个已知副作用**：重建 lockfile 后有 7 条 `resolved` 指向 `registry.npmjs.org`
（`@dcloudio/uni-app-plus` 及其依赖、`@vue/consolidate`、`licia`），其余指向 `registry.npmmirror.com`。
原因是**镜像上还没有那几个版本**，npm 自动回退到官方源（实测可成功安装）。

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

## 6. App 打包配置 ✅ 已配置（appid 待换正式值）

**已做**（`frontend/src/manifest.json`）：权限声明、应用标识与包名

- Android：`INTERNET`、`ACCESS_NETWORK_STATE`、`CAMERA`、`READ_EXTERNAL_STORAGE`、`WRITE_EXTERNAL_STORAGE`；
- iOS：`NSCameraUsageDescription`（拍摄办事材料）、`NSPhotoLibraryUsageDescription`（从相册选择）；
- `appid` = `one-stop-Agent`（项目名占位），Android `packagename` = `com.onestop.agent`。

**Android 明文 HTTP 已解决**（真机连 `http://<局域网IP>:8000` 必需，否则报 `CLEARTEXT_NOT_PERMITTED`）：

- `frontend/nativeResources/android/res/xml/network_security_config.xml`：放行明文；
- `frontend/AndroidManifest.xml`：以 `android:networkSecurityConfig` 引用之。
- ⚠️ 这两项**只在 HBuilderX 云打包时合并生效**——CLI 的 `uni build -p app` 不处理原生资源，
  云打包前需把 `nativeResources/` 与 `AndroidManifest.xml` 放到 HBuilderX 工程对应位置。

**App 端后端基址已配**：`frontend/.env.local` 写入 `VITE_API_BASE=http://10.195.130.130:8000`
（当前局域网 IP，该文件被 `.gitignore` 的 `*.local` 忽略、不入库）；换网络后改这里，或构建时注入。

**仍待办**：

- **`appid` 必须换成正式值**：DCloud 云打包只认开发者中心申请的 `__UNI__` 开头的 appid。
  当前 `one-stop-Agent` 只能用于占位 / 离线打包，直接云打包会因"应用标识无效"失败——请申请后替换；
- 上线前：改用 HTTPS，并把 `network_security_config.xml` 的 `cleartextTrafficPermitted` 收紧；
- 真机首次跑通后，建议再核一遍最终 APK 的权限清单（Android 13+ 对相册的权限模型有变化）；
- 打包命令已就绪且已验证：`npm run build:app`（产物在 `frontend/dist/build/app/`）。

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
| **第一次真机跑 App** | 填 `appid`、明文 HTTP 策略 | 第 0/1/2/3/6 条**已完成**，`npm run build:app` 已能产出产物 |
| **给多个真实用户用** | 4、5 | 大改（Redis + 数据库 + 鉴权） |

## 怎么验前端（`frontend/scripts/probe-h5.mjs`）

这个项目**没有前端自动化测试**。而第 0 条那个 bug 说明了：**"界面只更新一半"这类问题
靠读代码是推不出来的**——渲染中途抛错会让 DOM 停在半新半旧的状态，代码看着完全正确。

所以留了这个探测脚本：用无头 Chrome 打开 dev server，点一次场景切换，
把「胶囊 / 对话区标题 / 表单字段 / 两处必填提示」前后各读一遍，并收集控制台 error。

```bash
# 1) 起无头 Chrome（连远程调试端口）
"C:\Program Files\Google\Chrome\Application\chrome.exe" \
  --headless=new --disable-gpu --remote-debugging-port=9222 \
  --user-data-dir=..\data\runtime\cc-probe --no-first-run \
  --no-default-browser-check http://127.0.0.1:5173/

# 2) 跑探测（Node 20 需要显式打开 WebSocket）
node --experimental-websocket scripts/probe-h5.mjs 9222
```

判定标准：点「开办企业」后，胶囊应变成 `开办企业[*]`、标题应为「开办企业一件事」、
表单应为 7 个企业字段、提示应为 3 项企业字段，且**控制台无 error**。
`chips` 没变或字段数对不上，就说明渲染中途断了——先去控制台找 `TypeError`。

> 它不替代人工点测，但能在一秒内回答"界面到底更新完整了没有"，
> 而且能在**没有人盯着屏幕**的时候跑。改依赖、改模板之后建议跑一次。
