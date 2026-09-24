import type { ConditionPreview, MaterialView, Scenario } from '@/types/contract'

import { apiUrl } from './platform'

/**
 * 后端 HTTP 调用（跨端统一走 `uni.request`，见 `docs/10`）。
 *
 * **为什么不用 `fetch`**：
 * - App 端的 `fetch` 是 WebView 的原生 fetch，跨域受 CORS 限制，而后端**没有配 CORS**；
 *   `uni.request` 在 App 走 plus.net 原生，**不受 CORS 限制**；
 * - 各端统一（H5 走 XHR、App 走原生），不用为两端写两套；
 * - 相对路径的问题也一并解决：所有地址都过 `apiUrl()`，**不可能漏**（App 端没配基址会直接报错）。
 */

/** 可选场景（与 scenarios/*.json 对应） */
export const SCENARIOS = [
  { id: 'restaurant_open', name: '开办餐饮店' },
  { id: 'enterprise_open', name: '开办企业' }
]

type HttpMethod = 'GET' | 'POST' | 'DELETE'

interface RequestOptions {
  path: string
  method?: HttpMethod
  data?: any
  /** 后端没给 `detail` 时的兜底文案 */
  fallback?: string
}

/** 各端对 JSON 响应体处理不一致（H5 自动解析、部分端给字符串），统一成对象 */
function normalize(raw: any): any {
  if (typeof raw !== 'string') {
    return raw
  }
  try {
    return JSON.parse(raw)
  } catch (e) {
    return raw
  }
}

/** 取出后端给的用户可见说明（FastAPI 的错误体形如 `{"detail": "..."}`） */
function detailOf(raw: any): string {
  const data = normalize(raw)
  if (data && typeof data === 'object' && typeof data.detail === 'string') {
    return data.detail
  }
  return ''
}

/** 网络层失败（连不上 / 超时）说清是网络问题，别让用户以为是材料本身的问题 */
function failText(err: any): string {
  const message = err && err.errMsg ? String(err.errMsg) : ''
  if (message.indexOf('timeout') >= 0) {
    return '请求超时，请检查网络后重试'
  }
  return '连不上后端，请确认服务已启动、手机与后端在同一网络'
}

function request<T>(options: RequestOptions): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    uni.request({
      url: apiUrl(options.path),
      method: options.method || 'GET',
      data: options.data,
      header: options.data ? { 'Content-Type': 'application/json' } : {},
      success: (res: any) => {
        const status: number = res.statusCode || 0
        if (status >= 200 && status < 300) {
          resolve(normalize(res.data) as T)
          return
        }
        reject(new Error(detailOf(res.data)
          || (options.fallback || '请求失败') + '（' + status + '）'))
      },
      fail: (err: any) => reject(new Error(failText(err)))
    })
  })
}

export function fetchScenario(scenarioId: string): Promise<Scenario> {
  return request<Scenario>({
    path: '/scenarios/' + scenarioId,
    fallback: '场景加载失败'
  })
}

export function fetchCase(caseId: string): Promise<any> {
  return request<any>({
    path: '/api/cases/' + caseId,
    fallback: '未找到办理单 ' + caseId
  })
}

export interface AskResult {
  question: string
  answer: string
}

/** 会话信息（`POST /api/session` 的返回，界面只用到 session_id） */
export interface SessionInfo {
  session_id: string
  scenario_id: string
  scenario_name: string
  message: string
}

/**
 * 建会话。
 *
 * 对话区走会话之后才有**多轮上下文**——服务端按 session 记住前几轮问答
 * （见 `docs/08`）。表单式办理本身不依赖会话，所以只在用户第一次提问时懒建。
 */
export function createSession(scenarioId: string): Promise<SessionInfo> {
  return request<SessionInfo>({
    path: '/api/session',
    method: 'POST',
    data: { scenario_id: scenarioId },
    fallback: '会话创建失败'
  })
}

/** 对话区提问（咨询意图），返回自然语言回答；带 sessionId 才有上下文 */
export function askQuestion(
  scenarioId: string,
  question: string,
  sessionId = ''
): Promise<AskResult> {
  return request<AskResult>({
    path: '/api/ask',
    method: 'POST',
    data: { scenario_id: scenarioId, question, session_id: sessionId },
    fallback: '咨询失败'
  })
}

/**
 * 条件判定实时预判：按当前（可能还不完整的）表单预估事项与材料。
 *
 * 只读、无状态——不建材料收集单、不落库，所以可以随便调（前端做了防抖）。
 */
export function fetchPreview(
  scenarioId: string,
  answers: Record<string, any>
): Promise<ConditionPreview> {
  return request<ConditionPreview>({
    path: '/api/preview',
    method: 'POST',
    data: { scenario_id: scenarioId, answers },
    fallback: '预判失败'
  })
}

// ---------- 材料提交（受理前，见 docs/09）----------

/** 按申请信息判定所需材料，开一张材料收集单 */
export function createIntake(
  scenarioId: string,
  answers: Record<string, any>
): Promise<MaterialView> {
  return request<MaterialView>({
    path: '/api/materials/intake',
    method: 'POST',
    data: { scenario_id: scenarioId, answers },
    fallback: '材料清单生成失败'
  })
}

export function fetchIntake(intakeId: string): Promise<MaterialView> {
  return request<MaterialView>({
    path: '/api/materials/' + intakeId,
    fallback: '材料清单读取失败'
  })
}

/** 撤回一张材料 */
export function removeMaterialFile(
  intakeId: string,
  materialId: string,
  fileId: string
): Promise<MaterialView> {
  return request<MaterialView>({
    path: '/api/materials/' + intakeId + '/' + materialId + '/files/' + fileId,
    method: 'DELETE',
    fallback: '撤回失败'
  })
}

/**
 * 上传一张材料。
 *
 * 用 `uni.uploadFile` 而不是 `uni.request`：multipart 上传各端走原生
 * （H5 是 FormData、App 是原生上传器），能吃大图、不占 WebView 内存，
 * 同一份代码自动适配。文件由调用方通过 `uni.chooseImage`（拍照/相册）
 * 或 `uni.chooseFile`（文件管理）取得。
 */
export function uploadMaterialFile(
  intakeId: string,
  materialId: string,
  filePath: string,
  slot: string
): Promise<MaterialView> {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: apiUrl('/api/materials/' + intakeId + '/' + materialId + '/files'),
      filePath,
      name: 'file',
      formData: { slot },
      success: (res: any) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(normalize(res.data) as MaterialView)
          } catch (e) {
            reject(new Error('上传结果解析失败，请重试'))
          }
          return
        }
        reject(new Error(detailOf(res.data) || '上传失败（' + res.statusCode + '）'))
      },
      fail: (err: any) => reject(new Error(failText(err)))
    })
  })
}
