<script setup lang="ts">
/**
 * 线性图：把一串"要办的事 / 要交的材料"画成带流向的链条。
 *
 * 两种形态：
 * - `horizontal`：横向链（节点 + › 连接），宽屏一眼看全，长了可横滑；
 * - `vertical`  ：纵向时间线（左侧轨道 + 节点），窄列里全部可见，不用滑动。
 *
 * 状态四种：todo（待办）/ doing（进行中）/ done（已完成）/ warn（需补正）。
 */
export interface FlowStep {
  key: string
  title: string
  subtitle?: string
  badge?: string
  status: 'todo' | 'doing' | 'done' | 'warn'
}

withDefaults(
  defineProps<{
    steps: FlowStep[]
    direction?: 'horizontal' | 'vertical'
    emptyText?: string
  }>(),
  { direction: 'horizontal', emptyText: '暂无内容' }
)

const STATUS_ICON: Record<string, string> = {
  todo: '○',
  doing: '◐',
  done: '✔',
  warn: '!'
}

function icon(status: string): string {
  return STATUS_ICON[status] || '○'
}
</script>

<template>
  <view class="flow">
    <view v-if="!steps.length" class="flow__empty">
      <text>{{ emptyText }}</text>
    </view>

    <!-- 纵向时间线 -->
    <view v-else-if="direction === 'vertical'" class="vflow">
      <view v-for="(step, index) in steps" :key="step.key" class="vstep">
        <view class="vstep__rail">
          <text class="vstep__dot" :class="'vstep__dot--' + step.status">
            {{ icon(step.status) }}
          </text>
          <view
            v-if="index < steps.length - 1"
            class="vstep__line"
            :class="{ 'vstep__line--done': step.status === 'done' }"
          />
        </view>
        <view class="vstep__body">
          <view class="vstep__top">
            <text class="vstep__index">{{ index + 1 }}</text>
            <text class="vstep__title">{{ step.title }}</text>
            <text v-if="step.badge" class="vstep__badge" :class="'vstep__badge--' + step.status">
              {{ step.badge }}
            </text>
          </view>
          <text v-if="step.subtitle" class="vstep__sub">{{ step.subtitle }}</text>
        </view>
      </view>
    </view>

    <!-- 横向链 -->
    <scroll-view v-else class="flow__scroll" scroll-x :show-scrollbar="false">
      <view class="flow__track">
        <view v-for="(step, index) in steps" :key="step.key" class="flow__cell">
          <view class="flow__node" :class="'flow__node--' + step.status">
            <view class="flow__head">
              <text class="flow__icon">{{ icon(step.status) }}</text>
              <text class="flow__index">{{ index + 1 }}</text>
            </view>
            <text class="flow__title">{{ step.title }}</text>
            <text v-if="step.subtitle" class="flow__sub">{{ step.subtitle }}</text>
            <text v-if="step.badge" class="flow__badge" :class="'flow__badge--' + step.status">
              {{ step.badge }}
            </text>
          </view>
          <view
            v-if="index < steps.length - 1"
            class="flow__link"
            :class="{ 'flow__link--done': step.status === 'done' }"
          >
            <text class="flow__arrow">›</text>
          </view>
        </view>
      </view>
    </scroll-view>
  </view>
</template>

<style scoped>
.flow {
  width: 100%;
}

.flow__empty {
  padding: 6px 0;
  font-size: 12px;
  color: #9aa4b2;
}

/* ---------------- 纵向时间线 ---------------- */
.vflow {
  padding-top: 2px;
}

.vstep {
  display: flex;
  gap: 10px;
}

.vstep__rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 20px;
  flex: 0 0 20px;
}

.vstep__dot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  font-size: 11px;
  color: #9aa4b2;
  background: #f1f4f8;
  border-radius: 50%;
}

.vstep__dot--doing {
  color: #ffffff;
  background: #d97706;
}

.vstep__dot--done {
  color: #ffffff;
  background: #16a34a;
}

.vstep__dot--warn {
  color: #ffffff;
  background: #dc2626;
}

.vstep__line {
  flex: 1;
  width: 2px;
  min-height: 14px;
  background: #e2e8f0;
  border-radius: 2px;
}

.vstep__line--done {
  background: #9ad3b0;
}

.vstep__body {
  flex: 1;
  min-width: 0;
  padding-bottom: 10px;
}

.vstep__top {
  display: flex;
  align-items: center;
  gap: 6px;
}

.vstep__index {
  font-size: 10px;
  color: #b6bec9;
}

.vstep__title {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: #1f2329;
}

.vstep__sub {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  line-height: 16px;
  color: #8a94a3;
}

.vstep__badge {
  flex: 0 0 auto;
  padding: 1px 7px;
  font-size: 10px;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 999px;
}

.vstep__badge--doing {
  color: #b45309;
  background: #fdf3e3;
}

.vstep__badge--done {
  color: #15803d;
  background: #e8f6ed;
}

.vstep__badge--warn {
  color: #b91c1c;
  background: #fdeaea;
}

/* ---------------- 横向链 ---------------- */
.flow__scroll {
  width: 100%;
  white-space: nowrap;
}

.flow__track {
  display: inline-flex;
  align-items: stretch;
  padding: 2px 0 4px;
}

.flow__cell {
  display: flex;
  align-items: center;
}

.flow__node {
  display: flex;
  flex-direction: column;
  width: 132px;
  min-height: 74px;
  box-sizing: border-box;
  padding: 8px 10px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  white-space: normal;
}

.flow__node--doing {
  border-color: #f0c674;
  background: #fffdf5;
}

.flow__node--done {
  border-color: #b7e0c6;
  background: #f4fbf6;
}

.flow__node--warn {
  border-color: #f3b4b4;
  background: #fff7f7;
}

.flow__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.flow__icon {
  font-size: 12px;
  color: #9aa4b2;
}

.flow__node--doing .flow__icon {
  color: #d97706;
}

.flow__node--done .flow__icon {
  color: #16a34a;
}

.flow__node--warn .flow__icon {
  color: #dc2626;
}

.flow__index {
  font-size: 10px;
  color: #b6bec9;
}

.flow__title {
  font-size: 12px;
  font-weight: 600;
  line-height: 17px;
  color: #1f2329;
}

.flow__sub {
  margin-top: 2px;
  font-size: 11px;
  line-height: 15px;
  color: #8a94a3;
}

.flow__badge {
  align-self: flex-start;
  margin-top: 4px;
  padding: 1px 7px;
  font-size: 10px;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 999px;
}

.flow__badge--doing {
  color: #b45309;
  background: #fdf3e3;
}

.flow__badge--done {
  color: #15803d;
  background: #e8f6ed;
}

.flow__badge--warn {
  color: #b91c1c;
  background: #fdeaea;
}

.flow__link {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  color: #c7d0dd;
}

.flow__link--done {
  color: #7fc79a;
}

.flow__arrow {
  font-size: 16px;
  line-height: 1;
}
</style>
