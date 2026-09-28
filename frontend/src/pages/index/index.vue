<script setup lang="ts">
/**
 * 办理子页面：以「办理对话」为主体居中，右侧是可收起的详情栏。
 *
 * 对话是主线（像通用 AI 助手那样）；清单 / 申请信息 / 材料 / 进度属于支撑信息，
 * 放在右侧详情栏里，收起后对话占满整屏。
 */
import { computed, ref } from 'vue'

import { onBackPress, onLoad } from '@dcloudio/uni-app'

import ChatPanel from '@/components/ChatPanel.vue'
import ChecklistPanel from '@/components/ChecklistPanel.vue'
import DynamicForm from '@/components/DynamicForm.vue'
import MaterialPanel from '@/components/MaterialPanel.vue'
import ProgressBoard from '@/components/ProgressBoard.vue'
import { useCaseStore } from '@/stores/case'

const store = useCaseStore()
const queryId = ref('')
const showQuery = ref(false)
/** 右侧详情栏是否展开：默认收起，让对话居中当主体 */
const railOpen = ref(false)

const missingText = computed(() => store.missingFields.map((field) => field.label).join('、'))

const prepareLabel = computed(() => {
  if (store.preparing) {
    return '正在生成材料清单…'
  }
  if (!store.scenario) {
    return '加载中…'
  }
  return store.formComplete ? '下一步：提交材料' : '请先补全必填信息'
})

const submitLabel = computed(() => {
  if (store.running) {
    return '办理中…'
  }
  if (!store.materialsReady) {
    return '材料未齐（' + store.materialSummary.passed + '/' + store.materialSummary.total + '）'
  }
  return '开始办理'
})

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

/** 离开前的“要不要保存”弹窗（自绘：uni 的 H5 操作表会卡住并抛错） */
const leaveAsk = ref(false)

function onPrimary() {
  // 未填完 / 材料没齐：展开详情栏并告诉用户缺什么
  if (!store.intakeId) {
    if (!store.formComplete) {
      railOpen.value = true
      store.error = '请先在右侧「申请信息」里补全必填项：' + missingText.value
      return
    }
    store.prepare()
    return
  }
  if (!store.canSubmit) {
    railOpen.value = true
    store.error = store.materialsReady
      ? '正在办理中，请稍候'
      : '材料还没交齐，请在右侧「提交材料」里补齐'
    return
  }
  store.start()
}

/**
 * 离开办理页 → 回首页。
 *
 * 不用 navigateBack：H5 下它在应用内调用会被拒绝（promise reject），
 * 表现为“点了按钮却没反应”。reLaunch 不依赖页面栈，H5 与 App 行为一致；
 * 再做一层兜底，保证一定离得开。
 */
function leavePage() {
  setTimeout(() => {
    const goHome = () => {
      try {
        const r: any = uni.reLaunch({ url: '/pages/home/home' })
        if (r && typeof r.catch === 'function') {
          r.catch(() => {
            if (typeof window !== 'undefined') {
              window.location.hash = '#/pages/home/home'
            }
          })
        }
      } catch (e) {
        if (typeof window !== 'undefined') {
          window.location.hash = '#/pages/home/home'
        }
      }
    }
    goHome()
  }, 120)
}

function goBack() {
  if (!store.draftDirty) {
    leavePage()
    return
  }
  leaveAsk.value = true
}

/** 弹窗里的三个选择 */
function confirmLeave(action: 'save' | 'discard' | 'cancel') {
  leaveAsk.value = false
  if (action === 'cancel') {
    return
  }
  if (action === 'save') {
    store.saveDraft()
  } else {
    store.discardDraft()
  }
  leavePage()
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

onLoad(async (query: any) => {
  const scenarioId = query && query.scenario ? String(query.scenario) : ''
  const wantResume = !!(query && (query.resume === '1' || query.resume === 1))

  if (wantResume && store.checkDraft()) {
    await store.restoreDraft()
    return
  }
  if (scenarioId) {
    if (scenarioId === store.scenarioId && store.scenario) {
      return
    }
    await store.loadScenario(scenarioId)
    return
  }
  await store.loadScenario()
})

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', (event: BeforeUnloadEvent) => {
    if (!store.draftDirty) {
      return
    }
    event.preventDefault()
    event.returnValue = ''
  })
}

onBackPress(() => {
  if (!store.draftDirty) {
    return false
  }
  leaveAsk.value = true
  return true
})
</script>

<template>
  <view class="page">
    <!-- 顶栏 -->
    <view class="top">
      <view class="top__back" @click="goBack">
        <text class="top__back-icon">‹</text>
        <text class="top__back-text">返回</text>
      </view>

      <text class="top__name">{{ store.scenario ? store.scenario.name : '加载中…' }}</text>

      <view class="steps">
        <view class="step" :class="{ 'step--done': stepState.intake }">
          <text class="step__dot">1</text>
          <text class="step__text">填写信息</text>
        </view>
        <view class="step__line" :class="{ 'step__line--done': stepState.intake }" />
        <view class="step" :class="{ 'step--done': stepState.materials }">
          <text class="step__dot">2</text>
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
          <text class="step__dot">3</text>
          <text class="step__text">并联办理</text>
        </view>
      </view>

      <view class="top__actions">
        <text v-if="store.draftAvailable || store.draftDirty" class="top__hint">
          {{ store.draftAvailable ? '有草稿' : '未保存' }}
        </text>
        <view class="top__btn" @click="onSaveDraft">保存草稿</view>
        <view class="top__btn top__btn--ghost" @click="showQuery = !showQuery">查单号</view>
        <view class="top__btn top__btn--ghost" @click="railOpen = !railOpen">
          {{ railOpen ? '收起详情' : '详情' }}
        </view>
      </view>
    </view>

    <view v-if="showQuery" class="querybar">
      <input v-model="queryId" class="querybar__input" placeholder="输入办理单号回看，如 YJS0001" />
      <view class="querybar__btn" @click="store.query(queryId)">查询</view>
    </view>

    <!-- 主体：对话居中，详情栏在右（可收起） -->
    <view class="body">
      <view class="chatwrap">
        <view class="chatbox">
          <ChatPanel />
        </view>
      </view>

      <view v-if="railOpen" class="rail">
        <ChecklistPanel />
        <DynamicForm />
        <MaterialPanel />
        <ProgressBoard />
      </view>
    </view>

    <!-- 底部操作条 -->
    <view class="dock">
      <button
        class="btn"
        :class="{ 'btn--muted': !store.canSubmit && !store.preparing }"
        @click="onPrimary()"
      >
        {{ store.intakeId ? submitLabel : prepareLabel }}
      </button>

      <text v-if="store.missingFields.length" class="dock__hint">
        还差 {{ store.missingFields.length }} 项：{{ missingText }}
      </text>
    </view>

    <!-- 离开前的未保存提示 -->
    <view v-if="leaveAsk" class="mask">
      <view class="ask">
        <text class="ask__title">内容还没保存</text>
        <text class="ask__body">申请信息、对话记录和已传材料还没保存，离开后会丢失。</text>
        <view class="ask__btns">
          <view class="ask__btn ask__btn--primary" @click="confirmLeave('save')">保存草稿并离开</view>
          <view class="ask__btn ask__btn--danger" @click="confirmLeave('discard')">不保存，直接离开</view>
          <view class="ask__btn" @click="confirmLeave('cancel')">取消</view>
        </view>
      </view>
    </view>

    <view v-if="store.error" class="toast" @click="store.error = ''">
      <text>{{ store.error }}</text>
    </view>
  </view>
</template>

<style>
.page {
  display: flex;
  flex-direction: column;
  height: 100%;
  box-sizing: border-box;
  background: #eef2f8;
  overflow: hidden;
}

/* ---------------- 顶栏 ---------------- */
.top {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 0 0 auto;
  padding: 8px 16px;
  background: #ffffff;
  border-bottom: 1px solid #e3e9f2;
}

.top__back {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 10px 4px 4px;
  border-radius: 8px;
  background: #f2f6fd;
}

.top__back-icon {
  font-size: 16px;
  color: #1f6feb;
}

.top__back-text {
  font-size: 13px;
  color: #1f6feb;
}

.top__name {
  font-size: 16px;
  font-weight: 700;
  color: #1f2329;
  white-space: nowrap;
}

.steps {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.step {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px 3px 3px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
}

.step__dot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 10px;
  color: #6b7280;
  background: #eef1f5;
  border-radius: 50%;
}

.step__text {
  font-size: 11px;
  color: #6b7280;
  white-space: nowrap;
}

.step--on {
  border-color: #f0c674;
}

.step--on .step__dot {
  color: #ffffff;
  background: #d97706;
}

.step--on .step__text {
  color: #b45309;
}

.step--done {
  border-color: #b7e0c6;
  background: #f4fbf6;
}

.step--done .step__dot {
  color: #ffffff;
  background: #16a34a;
}

.step--done .step__text {
  color: #15803d;
}

.step__line {
  flex: 0 0 16px;
  height: 2px;
  background: #e2e8f0;
  border-radius: 2px;
}

.step__line--done {
  background: #9ad3b0;
}

.top__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.top__hint {
  font-size: 11px;
  color: #b45309;
}

.top__btn {
  padding: 5px 12px;
  font-size: 12px;
  color: #ffffff;
  background: #1f6feb;
  border-radius: 8px;
  white-space: nowrap;
}

.top__btn--ghost {
  color: #1f6feb;
  background: #ffffff;
  border: 1px solid #c3d6f7;
}

.querybar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
  padding: 8px 16px;
  background: #f7f9fc;
  border-bottom: 1px solid #e3e9f2;
}

.querybar__input {
  flex: 1;
  height: 32px;
  box-sizing: border-box;
  padding: 0 10px;
  font-size: 12px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.querybar__btn {
  padding: 6px 16px;
  font-size: 12px;
  color: #1f6feb;
  background: #ffffff;
  border: 1px solid #c3d6f7;
  border-radius: 8px;
}

/* ---------------- 主体 ---------------- */
.body {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  gap: 14px;
  padding: 14px 18px;
}

/* 对话区：占满剩余宽度，内容限宽居中，像通用 AI 助手 */
.chatwrap {
  display: flex;
  flex: 1 1 auto;
  justify-content: center;
  min-width: 0;
  min-height: 0;
}

.chatbox {
  display: flex;
  width: 100%;
  max-width: 760px;
  min-height: 0;
}

/* 右侧详情栏 */
.rail {
  display: flex;
  flex: 0 0 400px;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

/* ---------------- 底部条 ---------------- */
.dock {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
  padding: 11px 18px;
  background: #ffffff;
  border-top: 1px solid #e3e9f2;
  box-shadow: 0 -6px 16px rgba(15, 23, 42, 0.05);
}

.btn {
  flex: 0 0 320px;
  height: 38px;
  line-height: 38px;
  font-size: 14px;
  font-weight: 600;
  color: #ffffff;
  background: #1f6feb;
  border: none;
  border-radius: 9px;
}

.btn--muted {
  background: #a9c3ee;
  color: #f2f6ff;
  box-shadow: none;
}

.dock__hint {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: #b45309;
}

.mask {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0.45);
}

.ask {
  display: flex;
  flex-direction: column;
  width: 360px;
  padding: 22px 22px 16px;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 18px 40px rgba(15, 23, 42, 0.25);
}

.ask__title {
  font-size: 17px;
  font-weight: 700;
  color: #1f2329;
}

.ask__body {
  margin-top: 8px;
  font-size: 13px;
  line-height: 20px;
  color: #6b7280;
}

.ask__btns {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 18px;
}

.ask__btn {
  height: 38px;
  line-height: 38px;
  font-size: 14px;
  text-align: center;
  color: #4b5563;
  background: #f4f6fa;
  border-radius: 9px;
}

.ask__btn--primary {
  color: #ffffff;
  background: #1f6feb;
}

.ask__btn--danger {
  color: #b91c1c;
  background: #fdeaea;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 74px;
  transform: translateX(-50%);
  z-index: 20;
  max-width: min(80%, 460px);
  box-sizing: border-box;
  padding: 10px 16px;
  font-size: 13px;
  line-height: 20px;
  word-break: break-word;
  color: #ffffff;
  background: #ef4444;
  border-radius: 10px;
  box-shadow: 0 6px 20px rgba(239, 68, 68, 0.28);
}

/* 窄屏（含 App 竖屏）：对话在上，详情在下，整页可滚 */
@media (max-width: 900px) {
  .page {
    height: auto;
    min-height: 100vh;
    overflow: visible;
  }

  .body {
    flex-direction: column;
  }

  .chatbox {
    max-width: none;
    height: 520px;
  }

  .rail {
    flex: 1 1 auto;
    width: 100%;
    overflow: visible;
  }

  .steps {
    display: none;
  }

  .dock {
    position: sticky;
    bottom: 0;
  }

  .btn {
    flex: 1;
  }
}
</style>