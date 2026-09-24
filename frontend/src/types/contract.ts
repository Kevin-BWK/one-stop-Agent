/**
 * 前后端契约类型（前端侧）。
 *
 * 契约的**服务端定义**在 `server/schemas.py`（Pydantic 响应模型 + 路由的 `response_model`），
 * 事件负载来自 `app/orchestrator/events.py`，场景配置来自 `scenarios/*.json`。
 *
 * 两侧一致性由 `tests/test_openapi_contract.py` 守着：它拿后端 OpenAPI schema
 * 校验「本文件用到的字段，后端模型里都有」——后端改字段名会让那个测试失败，
 * 而不是让这里静默坏掉（见 docs/07）。
 */

export type FlowStatus = '待办' | '进行中' | '已完成'

export interface FlowNode {
  key: string
  name: string
  status: FlowStatus
  detail: string
  updated_at: string
}

/** flow_node 事件：节点快照 + 整体进度 */
export interface FlowNodePayload extends FlowNode {
  done: number
  total: number
}

/** message 事件：面向用户的文本 */
export interface MessagePayload {
  stage: string
  text: string
}

/** case_created 事件：并联提交生成办理单 */
export interface CaseCreatedPayload {
  case_id: string
  scenario_id: string
  items: string[]
  materials: string[]
}

/** item_done 事件：部门子 Agent 办结某事项 */
export interface ItemDonePayload {
  item_id: string
  name: string
  department: string
  output: string
  status: string
}

/** finished 事件：全流程结束 */
export interface FinishedPayload {
  case_id: string
  flow: FlowNode[]
  item_status: Record<string, string>
}

export interface ErrorPayload {
  code: string
  message: string
}

export type EventType =
  | 'message'
  | 'flow_node'
  | 'case_created'
  | 'item_done'
  | 'finished'
  | 'error'

/** 后端推送的统一事件外壳（Event.to_dict()） */
export interface OutboundEvent {
  type: EventType | string
  data: Record<string, any>
}

export interface CollectField {
  key: string
  label: string
  type: 'text' | 'enum' | 'number' | 'bool'
  options?: string[]
  required?: boolean
}

/**
 * 条件判定实时预判（POST /api/preview）。
 *
 * 按**目前填了多少**预估要办的事与要交的材料；只读、无副作用。
 * 信息采齐后会产出正式清单（`intake_id`），此时两者一致。
 */
export interface ConditionPreview {
  items: string[]
  item_names: string[]
  materials: string[]
  material_names: string[]
  /** 命中条件规则的说明（为什么多出这几项） */
  notes: string[]
}

/** 用户已提交的单个文件（材料区渲染缩略图用） */
export interface MaterialFile {
  file_id: string
  slot: string
  filename: string
  size: number
  status: string
  reason: string
  /** 读回地址，直接作为 <image src> 使用 */
  url: string
  uploaded_at: string
}

/** 一份材料：清单信息 + 提交状态 + 已传文件 */
export interface MaterialItem {
  id: string
  name: string
  /** 为什么要交 */
  reason: string
  /** 形式要求（怎么给） */
  form: string
  accept: string[]
  /** 具名槽位；空数组表示"多页材料"，张数上限看 max_files */
  slots: string[]
  multiple: boolean
  max_files: number
  required: boolean
  /** 待提交 / 已通过 / 需补正 */
  status: string
  missing_slots: string[]
  files: MaterialFile[]
}

export interface MaterialSummary {
  total: number
  passed: number
  ready: boolean
}

/** 材料收集单视图（POST /api/materials/intake 与各上传接口的统一返回） */
export interface MaterialView {
  intake_id: string
  scenario_id: string
  items: string[]
  notes: string[]
  summary: MaterialSummary
  materials: MaterialItem[]
  /** 对话区播报文案（仅创建时返回） */
  message?: string
}

export interface ScenarioItem {
  name: string
  department: string
  output: string
}

export interface Scenario {
  id: string
  name: string
  opening: string
  collect_fields: CollectField[]
  items: Record<string, ScenarioItem>
}

/** 聊天区一条消息 */
export interface ChatMessage {
  id: number
  stage: string
  text: string
}
