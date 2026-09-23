import { defineStore } from 'pinia'

import {
  askQuestion,
  createIntake,
  fetchCase,
  fetchScenario,
  removeMaterialFile,
  uploadMaterialFile
} from '@/api/http'
import { subscribeApply } from '@/api/stream'
import type {
  ChatMessage,
  CollectField,
  FlowNode,
  MaterialItem,
  MaterialSummary,
  MaterialView,
  OutboundEvent,
  Scenario
} from '@/types/contract'

let messageSeq = 0

function emptyAnswers(fields: CollectField[]): Record<string, any> {
  const answers: Record<string, any> = {}
  fields.forEach((field) => {
    if (field.type === 'bool') {
      answers[field.key] = false // 开关型给出明确默认值
    } else if (field.type === 'number') {
      answers[field.key] = null // 数字型留空，不用 0 冒充已填
    } else {
      answers[field.key] = ''
    }
  })
  return answers
}

/** 未填的必填项（前端提交前置校验） */
function missingRequired(
  scenario: Scenario | null,
  answers: Record<string, any>
): CollectField[] {
  if (!scenario) {
    return []
  }
  return scenario.collect_fields.filter((field) => {
    if (!field.required) {
      return false
    }
    const value = answers[field.key]
    if (value === null || value === undefined) {
      return true
    }
    return typeof value === 'string' && value.trim() === ''
  })
}

export const useCaseStore = defineStore('case', {
  state: () => ({
    scenarioId: 'restaurant_open',
    scenario: null as Scenario | null,
    answers: {} as Record<string, any>,
    utterance: '',
    opening: '' as string,
    messages: [] as ChatMessage[],
    nodes: [] as FlowNode[],
    done: 0,
    total: 0,
    itemStatus: {} as Record<string, string>,
    itemOutput: {} as Record<string, string>,
    caseId: '',
    /** 材料收集单号：填完信息、拿到材料清单后才有 */
    intakeId: '',
    materials: [] as MaterialItem[],
    materialSummary: { total: 0, passed: 0, ready: false } as MaterialSummary,
    /** 正在上传/撤回的那一项（`materialId|slot`），用于禁用按钮 */
    materialBusy: '',
    running: false,
    preparing: false,
    asking: false,
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
    },
    missingFields(state): CollectField[] {
      return missingRequired(state.scenario, state.answers)
    },
    /** 申请信息是否填齐（填齐才能进入材料提交） */
    formComplete(state): boolean {
      return !!state.scenario && missingRequired(state.scenario, state.answers).length === 0
    },
    /** 必交材料是否全部通过核验（通过才能并联提交） */
    materialsReady(state): boolean {
      return !!state.intakeId && state.materialSummary.ready
    },
    canSubmit(state): boolean {
      return (
        !!state.scenario &&
        !state.running &&
        missingRequired(state.scenario, state.answers).length === 0 &&
        !!state.intakeId &&
        state.materialSummary.ready
      )
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
        this.opening = scenario.opening || ''
        this.utterance = ''
        this.reset()
      } catch (e: any) {
        this.error = e && e.message ? e.message : '场景加载失败'
      } finally {
        this.loading = false
      }
    },

    reset() {
      this.messages = []
      this.intakeId = ''
      this.materials = []
      this.materialSummary = { total: 0, passed: 0, ready: false }
      this.materialBusy = ''
      this.resetProgress()
    },

    /** 只清办理过程的展示状态（对话与已交材料保留） */
    resetProgress() {
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

    /** 把用户填写的表单转成一句自然语言（既是"我说的话"，也作为意图识别输入） */
    describeAnswers(): string {
      const fields = this.scenario ? this.scenario.collect_fields : []
      const parts: string[] = []
      fields.forEach((field) => {
        const value = this.answers[field.key]
        if (value === null || value === undefined || value === '') {
          return
        }
        const human = typeof value === 'boolean' ? (value ? '是' : '否') : String(value)
        parts.push(field.label + '：' + human)
      })
      return '我要办理，申请信息如下 —— ' + parts.join('；')
    },

    /**
     * 第一段：提交申请信息，换取材料清单。
     *
     * 材料清单由条件判定产出（如面积 ≥300㎡ 才要消防材料），
     * 所以必须先跑完判定，才知道要交哪些材料，此时还没有受理。
     */
    async prepare() {
      if (this.preparing || this.running || !this.scenario) {
        return
      }
      const missing = missingRequired(this.scenario, this.answers)
      if (missing.length) {
        this.error = '还有必填信息没填：' + missing.map((field) => field.label).join('、')
        return
      }
      const utterance = this.describeAnswers()
      this.utterance = utterance
      this.preparing = true
      this.error = ''
      try {
        const view = await createIntake(this.scenarioId, this.answers)
        this.pushMessage('你', utterance)
        this.applyMaterialView(view)
        if (view.message) {
          this.pushMessage('材料Agent', view.message)
        }
      } catch (e: any) {
        this.error = e && e.message ? e.message : '材料清单生成失败'
      } finally {
        this.preparing = false
      }
    },

    /** 用后端返回的材料视图刷新本地状态（上传 / 撤回后统一走这里） */
    applyMaterialView(view: MaterialView) {
      this.intakeId = view.intake_id
      this.materials = view.materials
      this.materialSummary = view.summary
    },

    /** 拍照 / 从相册选一张：App 端能直接调摄像头，桌面浏览器会退化为选文件 */
    chooseImage(material: MaterialItem, slot: string) {
      uni.chooseImage({
        count: 1,
        sizeType: ['original'], // 要原图：压缩过的图容易被判为"看不清"
        sourceType: ['camera', 'album'],
        success: (res: any) => {
          const path = res.tempFilePaths && res.tempFilePaths[0]
          if (path) {
            this.uploadMaterial(material.id, slot, path)
          }
        },
        fail: () => undefined
      })
    },

    /** 从文件管理里选一张（PDF 等非图片材料走这里） */
    chooseFile(material: MaterialItem, slot: string) {
      uni.chooseFile({
        count: 1,
        extension: material.accept.map((ext) => '.' + ext),
        success: (res: any) => {
          const path = res.tempFilePaths && res.tempFilePaths[0]
          if (path) {
            this.uploadMaterial(material.id, slot, path)
          }
        },
        fail: () => undefined
      })
    },

    async uploadMaterial(materialId: string, slot: string, filePath: string) {
      if (!this.intakeId || this.materialBusy) {
        return
      }
      this.materialBusy = materialId + '|' + slot
      this.error = ''
      try {
        this.applyMaterialView(await uploadMaterialFile(this.intakeId, materialId, filePath, slot))
      } catch (e: any) {
        this.error = e && e.message ? e.message : '上传失败'
      } finally {
        this.materialBusy = ''
      }
    },

    async removeMaterial(materialId: string, fileId: string) {
      if (!this.intakeId || this.materialBusy) {
        return
      }
      this.materialBusy = materialId + '|' + fileId
      this.error = ''
      try {
        this.applyMaterialView(await removeMaterialFile(this.intakeId, materialId, fileId))
      } catch (e: any) {
        this.error = e && e.message ? e.message : '撤回失败'
      } finally {
        this.materialBusy = ''
      }
    },

    /** 第二段：材料齐备后开始办理，建立事件流边办边推 */
    start() {
      if (this.running || !this.scenario) {
        return
      }
      if (!this.intakeId) {
        this.error = '请先提交申请信息，拿到材料清单'
        return
      }
      if (!this.materialSummary.ready) {
        this.error =
          '材料还没交齐：已通过 ' + this.materialSummary.passed + '/' + this.materialSummary.total
        return
      }
      this.resetProgress()
      this.running = true
      this.closer = subscribeApply(
        {
          scenario_id: this.scenarioId,
          utterance: this.utterance,
          answers: this.answers,
          intake_id: this.intakeId
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

    /** 对话区提问：任何时候都能问，答完不影响正在填的信息 */
    async ask(question: string) {
      const text = (question || '').trim()
      if (!text || this.asking) {
        return
      }
      this.pushMessage('你', text)
      this.asking = true
      try {
        const result = await askQuestion(this.scenarioId, text)
        this.pushMessage('咨询Agent', result.answer)
      } catch (e: any) {
        this.error = e && e.message ? e.message : '咨询失败'
      } finally {
        this.asking = false
      }
    },

    /** 凭单号回看（回看历史办理单） */
    async query(caseId: string) {
      this.loading = true
      try {
        const found = await fetchCase(caseId.trim())
        this.caseId = found.case_id
        // 回看的是已受理的办理单，材料区与本次回看无关
        this.intakeId = ''
        this.materials = []
        this.materialSummary = { total: 0, passed: 0, ready: false }
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
