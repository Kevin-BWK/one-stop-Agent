import { defineStore } from 'pinia'

import { fetchCase, fetchScenario } from '@/api/http'
import { subscribeApply } from '@/api/stream'
import type {
  ChatMessage,
  CollectField,
  FlowNode,
  OutboundEvent,
  Scenario
} from '@/types/contract'

let messageSeq = 0

function emptyAnswers(fields: CollectField[]): Record<string, any> {
  const answers: Record<string, any> = {}
  fields.forEach((field) => {
    if (field.type === 'bool') {
      answers[field.key] = false
    } else if (field.type === 'number') {
      answers[field.key] = 0
    } else {
      answers[field.key] = ''
    }
  })
  return answers
}

export const useCaseStore = defineStore('case', {
  state: () => ({
    scenarioId: 'restaurant_open',
    scenario: null as Scenario | null,
    answers: {} as Record<string, any>,
    utterance: '',
    messages: [] as ChatMessage[],
    nodes: [] as FlowNode[],
    done: 0,
    total: 0,
    itemStatus: {} as Record<string, string>,
    itemOutput: {} as Record<string, string>,
    caseId: '',
    running: false,
    error: '',
    loading: false,
    closer: null as null | (() => void)
  }),

  getters: {
    fields(state): CollectField[] {
      return state.scenario ? state.scenario.collect_fields : []
    },
    itemsMap(state) {
      return state.scenario ? state.scenario.items : {}
    },
    percent(state): number {
      return state.total ? Math.round((state.done / state.total) * 100) : 0
    }
  },

  actions: {
    async loadScenario(scenarioId?: string) {
      const id = scenarioId || this.scenarioId
      this.loading = true
      this.error = ''
      try {
        const scenario = await fetchScenario(id)
        this.scenarioId = scenario.id
        this.scenario = scenario
        this.answers = emptyAnswers(scenario.collect_fields)
        this.utterance = scenario.opening || scenario.name
        this.reset()
      } catch (e: any) {
        this.error = e && e.message ? e.message : '场景加载失败'
      } finally {
        this.loading = false
      }
    },

    reset() {
      this.messages = []
      this.nodes = []
      this.done = 0
      this.total = 0
      this.itemStatus = {}
      this.itemOutput = {}
      this.caseId = ''
      this.error = ''
      if (this.closer) {
        this.closer()
        this.closer = null
      }
    },

    pushMessage(stage: string, text: string) {
      messageSeq += 1
      this.messages.push({ id: messageSeq, stage, text })
    },

    setAnswer(key: string, value: any) {
      this.answers[key] = value
    },

    /** 提交申请：建立事件流，边办边推 */
    start() {
      if (this.running || !this.scenario) {
        return
      }
      this.reset()
      this.running = true
      this.pushMessage('你', this.utterance)

      this.closer = subscribeApply(
        {
          scenario_id: this.scenarioId,
          utterance: this.utterance,
          answers: this.answers
        },
        {
          onEvent: (event: OutboundEvent) => this.handleEvent(event),
          onError: (message: string) => {
            this.error = message
            this.running = false
          },
          onClose: () => {
            this.running = false
          }
        }
      )
    },

    handleEvent(event: OutboundEvent) {
      const data = event.data || {}
      switch (event.type) {
        case 'message':
          this.pushMessage(String(data.stage || 'Agent'), String(data.text || ''))
          break
        case 'flow_node': {
          const node = data as unknown as FlowNode
          const exists = this.nodes.findIndex((item) => item.key === node.key)
          if (exists >= 0) {
            this.nodes.splice(exists, 1, node)
          } else {
            this.nodes.push(node)
          }
          this.done = Number(data.done || 0)
          this.total = Number(data.total || this.nodes.length)
          break
        }
        case 'case_created':
          this.caseId = String(data.case_id || '')
          this.itemStatus = {}
          ;(data.items || []).forEach((itemId: string) => {
            this.itemStatus[itemId] = '已受理'
          })
          break
        case 'item_done':
          this.itemStatus[String(data.item_id)] = String(data.status || '已办结')
          this.itemOutput[String(data.item_id)] = String(data.output || '')
          break
        case 'finished':
          this.caseId = String(data.case_id || this.caseId)
          if (Array.isArray(data.flow)) {
            this.nodes = data.flow as FlowNode[]
          }
          if (data.item_status) {
            this.itemStatus = { ...data.item_status }
          }
          this.running = false
          break
        case 'error':
          this.error = String(data.message || '编排失败')
          this.running = false
          break
        default:
          break
      }
    },

    /** 凭单号回看（回看历史办理单） */
    async query(caseId: string) {
      this.loading = true
      try {
        const found = await fetchCase(caseId.trim())
        this.caseId = found.case_id
        if (Array.isArray(found.flow)) {
          this.nodes = found.flow
        }
        this.itemStatus = { ...(found.item_status || {}) }
        this.utterance = ''
        this.running = false
        this.error = ''
      } catch (e: any) {
        this.error = e && e.message ? e.message : '查询失败'
      } finally {
        this.loading = false
      }
    }
  }
})
