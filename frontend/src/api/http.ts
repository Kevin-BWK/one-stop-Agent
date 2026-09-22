import type { Scenario } from '@/types/contract'

/** 可选场景（与 scenarios/*.json 对应） */
export const SCENARIOS = [
  { id: 'restaurant_open', name: '开办餐饮店' },
  { id: 'enterprise_open', name: '开办企业' }
]

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
