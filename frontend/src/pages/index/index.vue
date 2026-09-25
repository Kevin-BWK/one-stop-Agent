<script setup lang="ts">
import { onBackPress } from '@dcloudio/uni-app'
import { computed, onMounted, ref } from 'vue'

import { SCENARIOS } from '@/api/http'
import ChatPanel from '@/components/ChatPanel.vue'
import ChecklistPanel from '@/components/ChecklistPanel.vue'
import DynamicForm from '@/components/DynamicForm.vue'
import MaterialPanel from '@/components/MaterialPanel.vue'
import ProgressBoard from '@/components/ProgressBoard.vue'
import { useCaseStore } from '@/stores/case'

const store = useCaseStore()
const queryId = ref('')

const missingText = computed(() => store.missingFields.map((field) => field.label).join('、'))

/** 第一步：填完信息 -> 换取材料清单 */
const prepareLabel = computed(() => {
  if (store.preparing) {
    return '正在生成材料清单…'
  }
  if (!store.scenario) {
    return '加载中…'
  }
  return store.formComplete ? '下一步：提交材料' : '请先补全必填信息'
})

/** 第二步：材料齐备 -> 开始办理 */
const submitLabel = computed(() => {
  if (store.running) {
    return '办理中…'
  }
  if (!store.materialsReady) {
    return '材料未齐（' + store.materialSummary.passed + '/' + store.materialSummary.total + '）'
  }
  return '开始办理'
})

/** 顶部三步指示：填信息 -> 交材料 -> 并联办理 */
const stepState = computed(() => {
  const statuses = Object.values(store.itemStatus) as string[]
  const finished = !!store.caseId && statuses.length > 0 && statuses.every((s) => s === '已办结')
  return {
    intake: store.formComplete,
    materials: store.materialsReady,
    running: !!store.caseId,
    finished
  }
})

/**
 * 离开前问一句"要不要保存"。
 *
 * 用操作表而不是确认框：确认框只有两个按钮，塞不下
 * "保存 / 不保存 / 取消" 三种选择（取消＝留在当前页）。
 */
function askSaveDraft(after: (action: 'save' | 'discard' | 'cancel') => void) {
  uni.showActionSheet({
    itemList: ['保存草稿后离开', '不保存，直接离开'],
    success: (res: any) => {
      if (res.tapIndex === 0) {
        after('save')
      } else if (res.tapIndex === 1) {
        after('discard')
      } else {
        after('cancel')
      }
    },
    fail: () => after('cancel')
  })
}

/** 切换场景：手里有没保存的内容就先问一句，别把填好的冲掉 */
function onSwitchScenario(id: string) {
  if (id === store.scenarioId) {
    return
  }
  if (!store.draftDirty) {
    store.loadScenario(id)
    return
  }
  askSaveDraft((action) => {
    if (action === 'cancel') {
      return
    }
    if (action === 'save') {
      store.saveDraft()
    } else {
      store.discardDraft()
    }
    store.loadScenario(id)
  })
}

function onSaveDraft() {
  if (!store.draftDirty) {
    store.error = '还没有可保存的内容'
    return
  }
  if (store.saveDraft()) {
    uni.showToast({ title: '草稿已保存', icon: 'none' })
  }
}

onMounted(async () => {
  await store.loadScenario()
  if (store.checkDraft()) {
    uni.showModal({
      title: '发现未完成的草稿',
      content: '上次有没办完的内容，要接着办吗？',
      confirmText: '恢复草稿',
      cancelText: '重新开始',
      success: (res: any) => {
        if (res.confirm) {
          store.restoreDraft()
        }
      }
    })
  }
})

// 浏览器：刷新 / 关标签页 / 跳外链时用原生提示拦一下
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', (event: BeforeUnloadEvent) => {
    if (!store.draftDirty) {
      return
    }
    event.preventDefault()
    event.returnValue = ''
  })
}

// App / 小程序：返回键拦截，先问要不要保存
onBackPress(() => {
  if (!store.draftDirty) {
    return false
  }
  askSaveDraft((action) => {
    if (action === 'cancel') {
      return
    }
    if (action === 'save') {
      store.saveDraft()
    } else {
      store.discardDraft()
    }
    setTimeout(() => uni.navigateBack({ delta: 1 }), 60)
  })
  return true
})
</script>

<template>
  <view class="app">
    <view class="hero">
      <view class="hero__brand">
        <text class="hero__title">一件事 · 一次办</text>
        <text class="hero__sub">智能体协同办理 · 进度实时推送</text>
      </view>

      <view class="hero__scenarios">
        <view
          v-for="item in SCENARIOS"
          :key="item.id"
          class="chip"
          :class="{ 'chip--on': store.scenarioId === item.id }"
          @click="onSwitchScenario(item.id)"
        >
          <text>{{ item.name }}</text>
        </view>
      </view>
    </view>

    <view class="steps">
      <view class="step" :class="{ 'step--done': stepState.intake }">
        <text class="step__idx">1</text>
        <text class="step__text">填写信息</text>
      </view>
      <view class="step__line" :class="{ 'step__line--done': stepState.intake }" />
      <view class="step" :class="{ 'step--done': stepState.materials }">
        <text class="step__idx">2</text>
        <text class="step__text">提交材料</text>
      </view>
      <view class="step__line" :class="{ 'step__line--done': stepState.materials }" />
      <view
        class="step"
        :class="{
          'step--done': stepState.finished,
          'step--on': stepState.running && !stepState.finished
        }"
      >
        <text class="step__idx">3</text>
        <text class="step__text">并联办理</text>
      </view>
    </view>

    <view class="body">
      <view class="col col--chat">
        <ChatPanel />
      </view>

      <view class="col col--side">
        <ChecklistPanel />
        <DynamicForm />
        <MaterialPanel />
        <ProgressBoard />
      </view>
    </view>

    <view class="dock">
      <view class="dock__main">
        <!-- 第一步：填完信息，先换材料清单（清单由条件判定产出） -->
        <button
          v-if="!store.intakeId"
          class="btn"
          :disabled="!store.formComplete || store.preparing || store.running"
          @click="store.prepare()"
        >
          {{ prepareLabel }}
        </button>

        <!-- 第二步：材料齐备后才允许并联提交 -->
        <button v-else class="btn" :disabled="!store.canSubmit" @click="store.start()">
          {{ submitLabel }}
        </button>

        <button class="btn btn--ghost dock__save" @click="onSaveDraft">保存草稿</button>
      </view>

      <view class="dock__aside">
        <text v-if="store.missingFields.length" class="dock__hint">
          还差 {{ store.missingFields.length }} 项：{{ missingText }}
        </text>
        <view class="query">
          <input
            v-model="queryId"
            class="query__input"
            placeholder="输入办理单号回看，如 YJS0001"
          />
          <button class="btn btn--ghost query__btn" @click="store.query(queryId)">查询</button>
        </view>
      </view>
    </view>

    <view v-if="store.error" class="toast" @click="store.error = ''">
      <text>{{ store.error }}</text>
    </view>
  </view>
</template>

<style>
.app {
  min-height: 100vh;
  box-sizing: border-box;
  padding: 16px 20px 132px;
  background: #f2f5fa;
}

/* ---------------- 顶部 ---------------- */
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 16px 18px;
  background: linear-gradient(120deg, #1f6feb, #3f8cff 60%, #56a8ff);
  border-radius: 16px;
  box-shadow: 0 10px 24px rgba(31, 111, 235, 0.18);
}

.hero__brand {
  display: flex;
  flex-direction: column;
}

.hero__title {
  font-size: 20px;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 0.4px;
}

.hero__sub {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.82);
}

.hero__scenarios {
  display: flex;
  gap: 8px;
}

.chip {
  padding: 6px 14px;
  font-size: 13px;
  color: #1f6feb;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-radius: 999px;
}

.chip--on {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.9);
}

/* ---------------- 三步指示 ---------------- */
.steps {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14px 2px 0;
}

.step {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px 5px 6px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
}

.step__idx {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  font-size: 11px;
  color: #6b7280;
  background: #eef1f5;
  border-radius: 50%;
}

.step__text {
  font-size: 12px;
  color: #6b7280;
}

.step--on {
  border-color: #f0c674;
}

.step--on .step__text {
  color: #b45309;
}

.step--on .step__idx {
  color: #ffffff;
  background: #d97706;
}

.step--done {
  border-color: #b7e0c6;
  background: #f4fbf6;
}

.step--done .step__text {
  color: #15803d;
}

.step--done .step__idx {
  color: #ffffff;
  background: #16a34a;
}

.step__line {
  flex: 0 0 28px;
  height: 2px;
  background: #e2e8f0;
  border-radius: 2px;
}

.step__line--done {
  background: #9ad3b0;
}

/* ---------------- 主体 ---------------- */
.body {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-top: 14px;
}

.col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.col--chat {
  position: sticky;
  top: 16px;
  flex: 1 1 440px;
  min-width: 0;
  height: calc(100vh - 240px);
  min-height: 420px;
}

.col--side {
  flex: 0 0 430px;
}

/* 窄屏（含 App 竖屏）：单列堆叠，避免左右互相挤压 */
@media (max-width: 960px) {
  .app {
    padding: 12px 12px 150px;
  }

  .body {
    flex-direction: column;
  }

  .col--chat {
    position: static;
    flex: 1 1 auto;
    width: 100%;
    height: 420px;
  }

  .col--side {
    flex: 1 1 auto;
    width: 100%;
  }

  .steps {
    flex-wrap: wrap;
  }

  .dock {
    padding: 8px 12px 10px;
  }

  .dock__aside {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
  }

  .query {
    width: 100%;
  }

  .query__input {
    flex: 1;
    width: auto;
  }
}

/* ---------------- 底部操作条 ---------------- */
.dock {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 20px 12px;
  background: rgba(255, 255, 255, 0.94);
  border-top: 1px solid #e6ebf2;
  box-shadow: 0 -8px 20px rgba(15, 23, 42, 0.06);
}

.dock__main {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  max-width: 640px;
  margin: 0 auto;
}

.dock__aside {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  max-width: 640px;
  margin: 0 auto;
}

.dock__hint {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  line-height: 16px;
  color: #b45309;
}

.dock__save {
  flex: 0 0 96px;
}

.btn {
  flex: 1;
  height: 42px;
  line-height: 42px;
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
  background: #1f6feb;
  border: none;
  border-radius: 10px;
  box-shadow: 0 6px 14px rgba(31, 111, 235, 0.2);
}

.btn[disabled] {
  background: #a9c3ee;
  color: #f2f6ff;
  box-shadow: none;
}

.btn--ghost {
  color: #1f6feb;
  background: #ffffff;
  border: 1px solid #c3d6f7;
  box-shadow: none;
}

.query {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.query__input {
  width: 210px;
  height: 38px;
  box-sizing: border-box;
  padding: 0 12px;
  font-size: 13px;
  background: #f7f9fc;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}

.query__btn {
  flex: 0 0 76px;
  height: 38px;
  line-height: 38px;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 92px;
  transform: translateX(-50%);
  z-index: 20;
  /* 提示是整句话（说清"哪里不对 + 怎么改"），要能舒服地读多行 */
  max-width: min(80%, 460px);
  box-sizing: border-box;
  padding: 10px 16px;
  font-size: 13px;
  line-height: 20px;
  text-align: left;
  word-break: break-word;
  color: #ffffff;
  background: #ef4444;
  border-radius: 10px;
  box-shadow: 0 6px 20px rgba(239, 68, 68, 0.28);
}
</style>
