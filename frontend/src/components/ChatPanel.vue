<script setup lang="ts">
import { computed, ref } from 'vue'

import { useCaseStore } from '@/stores/case'

const store = useCaseStore()
const draft = ref('')

const scrollInto = computed(() => {
  const list = store.messages
  return list.length ? 'msg-' + list[list.length - 1].id : ''
})

/** 把内部 Agent 名换成群众看得懂的称呼 */
const STAGE_LABEL: Record<string, string> = {
  咨询Agent: '办事助手',
  信息采集Agent: '办事助手',
  条件判定Agent: '办事助手',
  材料核验Agent: '办事助手',
  主Agent: '办事助手',
  进度Agent: '办事助手',
  部门子Agent: '部门反馈',
  你: '我'
}

function label(stage: string): string {
  return STAGE_LABEL[stage] || stage
}

function send() {
  const text = draft.value.trim()
  if (!text || store.asking) {
    return
  }
  draft.value = ''
  store.ask(text)
}

function useOpening() {
  if (store.opening) {
    draft.value = store.opening
  }
}
</script>

<template>
  <view class="chat">
    <view class="chat__head">
      <text class="chat__title">办理对话</text>
      <text class="chat__sub">{{ store.scenario ? store.scenario.name : '加载中…' }}</text>
    </view>

    <scroll-view class="chat__body" scroll-y :scroll-into-view="scrollInto" :scroll-with-animation="true">
      <view v-if="!store.messages.length" class="chat__empty">
        <text>可以直接点「开始办理」，也可以先问我任何问题，比如「需要什么材料」「流程是怎样的」。</text>
      </view>

      <view
        v-for="msg in store.messages"
        :id="'msg-' + msg.id"
        :key="msg.id"
        class="bubble"
        :class="msg.stage === '你' ? 'bubble--me' : 'bubble--agent'"
      >
        <text class="bubble__stage">{{ label(msg.stage) }}</text>
        <text class="bubble__text">{{ msg.text }}</text>
      </view>

      <view v-if="store.asking" class="bubble bubble--agent">
        <text class="bubble__stage">办事助手</text>
        <text class="bubble__text bubble__text--dim">正在查看办事指南…</text>
      </view>
    </scroll-view>

    <view class="chat__foot">
      <view v-if="!store.messages.length && store.opening" class="chat__chips">
        <text class="chip" @click="useOpening">试试：{{ store.opening }}</text>
      </view>
      <view class="chat__input">
        <input
          v-model="draft"
          class="chat__input-box"
          placeholder="有问题随时问我，比如「需要什么材料」"
          :disabled="store.asking"
          confirm-type="send"
          @confirm="send"
        />
        <button class="chat__send" :disabled="store.asking || !draft.trim()" @click="send">发送</button>
      </view>
    </view>
  </view>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  overflow: hidden;
}

.chat__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #eef1f5;
}

.chat__title {
  font-size: 15px;
  font-weight: 600;
}

.chat__sub {
  font-size: 12px;
  color: #6b7280;
}

.chat__body {
  flex: 1;
  min-height: 0;
  padding: 12px 16px;
  background: #fbfcfe;
}

.chat__empty {
  padding: 20px 8px;
  font-size: 13px;
  line-height: 20px;
  color: #9aa4b2;
}

.bubble {
  display: flex;
  flex-direction: column;
  max-width: 92%;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 10px;
}

.bubble--me {
  margin-left: auto;
  background: #1f6feb;
}

.bubble--me .bubble__stage,
.bubble--me .bubble__text {
  color: #ffffff;
}

.bubble--agent {
  margin-right: auto;
  background: #ffffff;
  border: 1px solid #e5e7eb;
}

.bubble__stage {
  font-size: 11px;
  color: #6b7280;
  margin-bottom: 4px;
}

.bubble__text {
  font-size: 13px;
  line-height: 20px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #1f2329;
}

.bubble__text--dim {
  color: #9aa4b2;
}

.chat__foot {
  padding: 10px 12px 12px;
  border-top: 1px solid #eef1f5;
  background: #ffffff;
}

.chat__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.chip {
  padding: 4px 10px;
  font-size: 12px;
  color: #1f6feb;
  background: #eef4ff;
  border: 1px solid #cfe0ff;
  border-radius: 999px;
}

.chat__input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat__input-box {
  flex: 1;
  height: 36px;
  box-sizing: border-box;
  padding: 0 12px;
  font-size: 13px;
  background: #f7f9fc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.chat__send {
  flex: 0 0 72px;
  height: 36px;
  line-height: 36px;
  font-size: 13px;
  color: #ffffff;
  background: #1f6feb;
  border: none;
  border-radius: 10px;
}

.chat__send[disabled] {
  background: #c7d6f2;
  color: #f4f7ff;
}
</style>
