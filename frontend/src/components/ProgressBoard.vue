<script setup lang="ts">
import { computed } from 'vue'

import { useCaseStore } from '@/stores/case'

const store = useCaseStore()

const ICON: Record<string, string> = {
  待办: '○',
  进行中: '◐',
  已完成: '✔'
}

const itemIds = computed(() => Object.keys(store.itemStatus))

function itemName(itemId: string): string {
  const meta = store.itemsMap[itemId]
  return meta ? meta.name : itemId
}

function itemDept(itemId: string): string {
  const meta = store.itemsMap[itemId]
  return meta ? meta.department : ''
}
</script>

<template>
  <view class="board">
    <view class="board__head">
      <text class="board__title">办理进度</text>
      <text class="board__count">{{ store.done }}/{{ store.total }}</text>
    </view>

    <view class="bar">
      <view class="bar__fill" :style="{ width: store.percent + '%' }" />
    </view>

    <scroll-view class="board__body" scroll-y>
      <view v-if="!store.nodes.length" class="board__empty">
        <text>尚未开始，流程节点会在办理时逐个打勾。</text>
      </view>

      <view
        v-for="node in store.nodes"
        :key="node.key"
        class="node"
        :class="'node--' + node.status"
      >
        <text class="node__icon">{{ ICON[node.status] || '○' }}</text>
        <view class="node__main">
          <text class="node__name">{{ node.name }}</text>
          <text v-if="node.detail" class="node__detail">{{ node.detail }}</text>
        </view>
        <text class="node__status">{{ node.status }}</text>
      </view>

      <view v-if="itemIds.length" class="items">
        <text class="items__title">并联办理</text>
        <view v-for="itemId in itemIds" :key="itemId" class="item">
          <view class="item__main">
            <text class="item__name">{{ itemName(itemId) }}</text>
            <text class="item__dept">{{ itemDept(itemId) }}</text>
          </view>
          <text class="item__status" :class="{ 'item__status--done': store.itemStatus[itemId] === '已办结' }">
            {{ store.itemStatus[itemId] }}
          </text>
        </view>
      </view>
    </scroll-view>

    <view v-if="store.caseId" class="board__foot">
      <text>办理单号：</text>
      <text class="board__case">{{ store.caseId }}</text>
    </view>
  </view>
</template>

<style scoped>
.board {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
}

.board__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 12px 16px 8px;
}

.board__title {
  font-size: 15px;
  font-weight: 600;
}

.board__count {
  font-size: 12px;
  color: #6b7280;
}

.bar {
  height: 6px;
  margin: 0 16px 10px;
  background: #eef1f5;
  border-radius: 999px;
  overflow: hidden;
}

.bar__fill {
  height: 100%;
  background: linear-gradient(90deg, #1f6feb, #3fb950);
  border-radius: 999px;
  transition: width 0.3s ease;
}

.board__body {
  flex: 1;
  min-height: 0;
  max-height: 320px;
  padding: 0 16px 12px;
}

.board__empty {
  padding: 16px 0;
  font-size: 13px;
  color: #9aa4b2;
}

.node {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px dashed #f0f2f5;
}

.node__icon {
  width: 18px;
  font-size: 14px;
  color: #9aa4b2;
  text-align: center;
}

.node--已完成 .node__icon {
  color: #16a34a;
}

.node--进行中 .node__icon {
  color: #d97706;
}

.node__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.node__name {
  font-size: 13px;
  color: #1f2329;
}

.node__detail {
  font-size: 11px;
  color: #9aa4b2;
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.node__status {
  font-size: 11px;
  color: #6b7280;
}

.node--已完成 .node__status {
  color: #16a34a;
}

.node--进行中 .node__status {
  color: #d97706;
}

.items {
  margin-top: 12px;
}

.items__title {
  font-size: 12px;
  font-weight: 600;
  color: #4b5563;
}

.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 0;
}

.item__main {
  display: flex;
  flex-direction: column;
}

.item__name {
  font-size: 13px;
  color: #1f2329;
}

.item__dept {
  font-size: 11px;
  color: #9aa4b2;
}

.item__status {
  font-size: 12px;
  color: #d97706;
}

.item__status--done {
  color: #16a34a;
}

.board__foot {
  padding: 10px 16px;
  border-top: 1px solid #eef1f5;
  font-size: 12px;
  color: #6b7280;
  background: #fbfcfe;
}

.board__case {
  color: #1f6feb;
  font-weight: 600;
}
</style>
