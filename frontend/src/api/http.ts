import type { MaterialView, Scenario } from '@/types/contract'

/**
 * 后端地址前缀。H5 调试端走 vite 代理，留空用相对路径即可；
 * 打包 App 时改成后端绝对地址（如 http://192.168.1.10:8000）。
 */
const API_BASE = ''

/** 可选场景（与 scenarios/*.json 对应） */
export const SCENARIOS = [
  { id: 'restaurant_open', name: '开办餐饮店' },
  { id: 'enterprise_open', name: '开办企业' }
]

/** 从后端错误响应里取出对用户友好的说明 */
async function errorText(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json()
    if (data && typeof data.detail === 'string') {
      return data.detail
    }
  } catch (e) {
    // 响应不是 JSON，用兜底文案
  }
  return fallback + '（' + res.status + '）'
}

function parseDetail(raw: unknown): string {
  if (typeof raw !== 'string') {
    return ''
  }
  try {
    const data = JSON.parse(raw)
    return data && typeof data.detail === 'string' ? data.detail : ''
  } catch (e) {
    return ''
  }
}

export async function fetchScenario(scenarioId: string): Promise<Scenario> {
  const res = await fetch('/scenarios/' + scenarioId)
  if (!res.ok) {
    throw new Error('场景加载失败（' + res.status + '）')
  }
  return (await res.json()) as Scenario
}

export async function fetchCase(caseId: string) {
  const res = await fetch('/api/cases/' + caseId)
  if (!res.ok) {
    throw new Error('未找到办理单 ' + caseId)
  }
  return await res.json()
}

export interface AskResult {
  question: string
  answer: string
}

/** 对话区提问（咨询意图），返回自然语言回答 */
export async function askQuestion(scenarioId: string, question: string): Promise<AskResult> {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_id: scenarioId, question })
  })
  if (!res.ok) {
    throw new Error('咨询失败（' + res.status + '）')
  }
  return (await res.json()) as AskResult
}

// ---------- 材料提交（受理前，见 docs/09）----------

/** 按申请信息判定所需材料，开一张材料收集单 */
export async function createIntake(
  scenarioId: string,
  answers: Record<string, any>
): Promise<MaterialView> {
  const res = await fetch(API_BASE + '/api/materials/intake', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_id: scenarioId, answers })
  })
  if (!res.ok) {
    throw new Error(await errorText(res, '材料清单生成失败'))
  }
  return (await res.json()) as MaterialView
}

export async function fetchIntake(intakeId: string): Promise<MaterialView> {
  const res = await fetch(API_BASE + '/api/materials/' + intakeId)
  if (!res.ok) {
    throw new Error(await errorText(res, '材料清单读取失败'))
  }
  return (await res.json()) as MaterialView
}

/** 撤回一张材料 */
export async function removeMaterialFile(
  intakeId: string,
  materialId: string,
  fileId: string
): Promise<MaterialView> {
  const res = await fetch(
    API_BASE + '/api/materials/' + intakeId + '/' + materialId + '/files/' + fileId,
    { method: 'DELETE' }
  )
  if (!res.ok) {
    throw new Error(await errorText(res, '撤回失败'))
  }
  return (await res.json()) as MaterialView
}

/**
 * 上传一张材料。
 *
 * 用 `uni.uploadFile` 而不是 fetch：它在各端统一走原生上传
 * （H5 是 FormData、App 是原生上传器），同一份代码自动适配，
 * 且能拿到上传进度。文件由调用方通过 `uni.chooseImage`（拍照/相册）
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
      url: API_BASE + '/api/materials/' + intakeId + '/' + materialId + '/files',
      filePath,
      name: 'file',
      formData: { slot },
      success: (res: any) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(res.data) as MaterialView)
          } catch (e) {
            reject(new Error('上传结果解析失败，请重试'))
          }
          return
        }
        reject(new Error(parseDetail(res.data) || '上传失败（' + res.statusCode + '）'))
      },
      fail: () => reject(new Error('上传失败，请检查网络后重试'))
    })
  })
}
