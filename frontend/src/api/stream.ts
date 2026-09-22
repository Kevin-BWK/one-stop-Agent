/**
 * 事件流订阅：后端"边办边推"，不是回放也不是轮询。
 *
 * - H5（调试端）：EventSource（SSE）→ `GET /apply`
 * - App（成品端）：uni.connectSocket（WebSocket）→ `/ws/apply`
 * 两端事件负载完全一致（Event.to_dict() 的 JSON）。
 */
import type { OutboundEvent } from '@/types/contract'

export interface ApplyPayload {
  scenario_id: string
  utterance: string
  answers: Record<string, any>
}

export interface StreamHandlers {
  onOpen?: () => void
  onEvent: (event: OutboundEvent) => void
  onError?: (message: string) => void
  onClose?: () => void
}

const EVENT_TYPES = ['message', 'flow_node', 'case_created', 'item_done', 'finished', 'error']

const TERMINAL = ['finished', 'error']

export function isH5(): boolean {
  return typeof window !== 'undefined' && typeof (window as any).EventSource !== 'undefined'
}

/** H5：SSE */
function subscribeBySse(payload: ApplyPayload, handlers: StreamHandlers) {
  const query = new URLSearchParams({
    scenario_id: payload.scenario_id,
    utterance: payload.utterance,
    answers: JSON.stringify(payload.answers)
  })

  let closed = false
  let source: EventSource
  const close = () => {
    if (!closed) {
      closed = true
      source.close()
    }
  }

  const handle = (event: OutboundEvent) => {
    handlers.onEvent(event)
    if (TERMINAL.indexOf(String(event.type)) >= 0) {
      close()
      handlers.onClose && handlers.onClose()
    }
  }

  source = new EventSource('/apply?' + query.toString())
  source.onopen = () => handlers.onOpen && handlers.onOpen()
  source.onerror = () => {
    if (!closed) {
      close()
      handlers.onError && handlers.onError('事件流连接中断')
      handlers.onClose && handlers.onClose()
    }
  }
  EVENT_TYPES.forEach((type) => {
    source.addEventListener(type, (evt: any) => {
      try {
        handle(JSON.parse(evt.data))
      } catch (e) {
        // 忽略无法解析的帧
      }
    })
  })

  return close
}

/** App：WebSocket */
function subscribeBySocket(payload: ApplyPayload, handlers: StreamHandlers) {
  const scheme = location.protocol === 'https:' ? 'wss://' : 'ws://'
  const task = uni.connectSocket({
    url: scheme + location.host + '/ws/apply'
  })

  let closed = false
  const close = () => {
    if (!closed) {
      closed = true
      task.close({})
    }
  }

  task.onOpen(() => {
    handlers.onOpen && handlers.onOpen()
    task.send({ data: JSON.stringify(payload) })
  })
  task.onMessage((res) => {
    let event: OutboundEvent
    try {
      event = JSON.parse(res.data as string)
    } catch (e) {
      return
    }
    handlers.onEvent(event)
    if (TERMINAL.indexOf(String(event.type)) >= 0) {
      close()
      handlers.onClose && handlers.onClose()
    }
  })
  task.onError(() => {
    handlers.onError && handlers.onError('WebSocket 连接失败')
  })
  task.onClose(() => handlers.onClose && handlers.onClose())

  return close
}

/** 按运行端自动选择传输载体 */
export function subscribeApply(payload: ApplyPayload, handlers: StreamHandlers) {
  return isH5() ? subscribeBySse(payload, handlers) : subscribeBySocket(payload, handlers)
}
