<script setup lang="ts">
import { computed } from 'vue'

import { useCaseStore } from '@/stores/case'

const store = useCaseStore()

const scrollInto = computed(() => {
  const list = store.messages
  return list.length ? 'msg-' + list[list.length - 1].id : ''
})
</script>

<template>
  <view class="chat">
    <view class="chat__head">
      <text class="chat__title">办理对话</text>
      <text class="chat__sub">{{ store.scenario ? store.scenario.name : '加载中…' }}</text>
    </view>

    <scroll-view class="chat__body" scroll-y :scroll-into-view="scrollInto" :scroll-with-animation="true">
      <view v-if="!store.messages.length" class="chat__empty">
        <text>选择场景 → 填写申请信息 → 点「开始办理」，办理过程会实时出现在这里。</text>
      </view>

      <view
        v-for="msg in store.messages"
        :id="'msg-' + msg.id"
        :key="msg.id"
        class="bubble"
        :class="msg.stage === '你' ? 'bubble--me' : 'bubble--agent'"
      >
        <text class="bubble__stage">{{ msg.stage }}</text>
        <text class="bubble__text">{{ msg.text }}</text>
      </view>
    </scroll-view>
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
  padding: 24px 8px;
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
</style>
