<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { SCENARIOS } from '@/api/http'
import ChatPanel from '@/components/ChatPanel.vue'
import DynamicForm from '@/components/DynamicForm.vue'
import ProgressBoard from '@/components/ProgressBoard.vue'
import { useCaseStore } from '@/stores/case'

const store = useCaseStore()
const queryId = ref('')

onMounted(() => {
  store.loadScenario()
})
</script>

<template>
  <view class="app">
    <view class="app__bar">
      <view class="app__brand">
        <text class="app__title">一件事 · 一次办</text>
        <text class="app__sub">uni-app (Vue 3 + TS) ｜ 办理过程由后端事件流实时推送</text>
      </view>

      <view class="app__scenarios">
        <view
          v-for="item in SCENARIOS"
          :key="item.id"
          class="chip"
          :class="{ 'chip--on': store.scenarioId === item.id }"
          @click="store.loadScenario(item.id)"
        >
          <text>{{ item.name }}</text>
        </view>
      </view>
    </view>

    <view class="app__body">
      <view class="col col--left">
        <ChatPanel />

        <view class="actions">
          <button class="btn" :disabled="store.running || !store.scenario" @click="store.start()">
            {{ store.running ? '办理中…' : '开始办理' }}
          </button>

          <view class="query">
            <input
              v-model="queryId"
              class="query__input"
              placeholder="输入办理单号回看，如 YJS0001"
            />
            <button class="btn btn--ghost" @click="store.query(queryId)">查询</button>
          </view>
        </view>
      </view>

      <view class="col col--right">
        <DynamicForm />
        <ProgressBoard />
      </view>
    </view>

    <view v-if="store.error" class="toast">
      <text>{{ store.error }}</text>
    </view>
  </view>
</template>

<style>
.app {
  min-height: 100vh;
  padding: 16px 20px 28px;
  box-sizing: border-box;
  background: #f5f7fb;
}

.app__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}

.app__brand {
  display: flex;
  flex-direction: column;
}

.app__title {
  font-size: 20px;
  font-weight: 700;
  color: #1f2329;
}

.app__sub {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}

.app__scenarios {
  display: flex;
  gap: 8px;
}

.chip {
  padding: 6px 14px;
  font-size: 13px;
  color: #4b5563;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
}

.chip--on {
  color: #ffffff;
  background: #1f6feb;
  border-color: #1f6feb;
}

.app__body {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.col--left {
  flex: 1 1 460px;
  min-width: 0;
  height: calc(100vh - 140px);
}

.col--right {
  flex: 0 0 400px;
}

/* 窄屏（含 App 竖屏）：单列堆叠，避免左右互相挤压 */
@media (max-width: 960px) {
  .app {
    padding: 12px 12px 24px;
  }

  .app__body {
    flex-direction: column;
  }

  .col--left {
    flex: 1 1 auto;
    width: 100%;
    height: 420px;
  }

  .col--right {
    flex: 1 1 auto;
    width: 100%;
  }
}

.actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.btn {
  height: 40px;
  line-height: 40px;
  font-size: 14px;
  color: #ffffff;
  background: #1f6feb;
  border-radius: 10px;
  border: none;
}

.btn[disabled] {
  background: #9db8e8;
  color: #f2f6ff;
}

.btn--ghost {
  flex: 0 0 84px;
  height: 36px;
  line-height: 36px;
  font-size: 13px;
  color: #1f6feb;
  background: #ffffff;
  border: 1px solid #bcd0f5;
}

.query {
  display: flex;
  gap: 8px;
}

.query__input {
  flex: 1;
  height: 36px;
  box-sizing: border-box;
  padding: 0 12px;
  font-size: 13px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  max-width: 80%;
  padding: 10px 16px;
  font-size: 13px;
  color: #ffffff;
  background: #ef4444;
  border-radius: 10px;
  box-shadow: 0 6px 20px rgba(239, 68, 68, 0.28);
}
</style>
