/// <reference types="vite/client" />

/**
 * 构建时注入的环境变量（vite 只暴露 `VITE_` 前缀的）。
 * 目前只用到 `VITE_API_BASE`，见 `src/api/platform.ts`。
 */
interface ImportMetaEnv {
  /** 后端基址；H5 调试端留空走代理，App 成品端**必须**填绝对地址 */
  readonly VITE_API_BASE?: string
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
