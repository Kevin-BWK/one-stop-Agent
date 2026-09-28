<script setup lang="ts">
/**
 * 首页：只负责“选办哪件事”。
 *
 * 办理过程在 /pages/index/index 子页面，这里保持一屏、一行一个场景。
 */
import { ref } from 'vue'

import { onShow } from '@dcloudio/uni-app'

import { SCENARIOS } from '@/api/http'
import { useCaseStore } from '@/stores/case'

const store = useCaseStore()
const hasDraft = ref(false)

/** 场景一览，帮助用户快速判断该点哪个 */
const BLURB: Record<string, string> = {
  restaurant_open: '营业执照 · 食品经营许可 · 健康证 · 消防 · 招牌',
  enterprise_open: '设立登记 · 税务 · 社保 · 公章刻制 · 银行开户'
}

onShow(() => {
  hasDraft.value = store.checkDraft()
})

function open(id: string) {
  uni.navigateTo({ url: '/pages/index/index?scenario=' + id })
}

function resume() {
  uni.navigateTo({ url: '/pages/index/index?resume=1' })
}
</script>

<template>
  <view class="home">
    <view class="inner">
      <view class="head">
        <text class="head__title">一件事 · 一次办</text>
        <text class="head__sub">基于移动云 MoMA 的多 Agent 协同办理</text>
      </view>

      <view v-if="hasDraft" class="resume" @click="resume">
        <text class="resume__icon">↻</text>
        <text class="resume__text">继续上次未完成的办理</text>
        <text class="row__arrow">›</text>
      </view>

      <view class="list">
        <view v-for="item in SCENARIOS" :key="item.id" class="row" @click="open(item.id)">
          <text class="row__name">{{ item.name }}</text>
          <text class="row__blurb">{{ BLURB[item.id] || '' }}</text>
          <text class="row__arrow">›</text>
        </view>
      </view>

      <text class="foot">一次申请 → 并联办理 → 一次出件</text>
    </view>
  </view>
</template>

<style scoped>
.home {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  box-sizing: border-box;
  padding: 24px;
  background: #f2f5fa;
}

.inner {
  width: 100%;
  max-width: 680px;
}

.head {
  display: flex;
  flex-direction: column;
  margin-bottom: 20px;
}

.head__title {
  font-size: 24px;
  font-weight: 700;
  color: #1f2329;
  letter-spacing: 0.5px;
}

.head__sub {
  margin-top: 6px;
  font-size: 13px;
  color: #7b8798;
}

.resume {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  padding: 12px 16px;
  background: #fff8e8;
  border: 1px solid #f0dcb0;
  border-radius: 10px;
}

.resume__icon {
  font-size: 14px;
  color: #b08a4a;
}

.resume__text {
  flex: 1;
  font-size: 14px;
  color: #92400e;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.row:active {
  border-color: #1f6feb;
  background: #f7faff;
}

.row__name {
  flex: 0 0 128px;
  font-size: 16px;
  font-weight: 600;
  color: #1f2329;
}

.row__blurb {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  line-height: 18px;
  color: #7b8798;
}

.row__arrow {
  flex: 0 0 auto;
  font-size: 18px;
  color: #b6c0cd;
}

.foot {
  display: block;
  margin-top: 18px;
  font-size: 12px;
  color: #9aa4b2;
  text-align: center;
}

/* 窄屏（含 App 竖屏）：名称与说明上下排 */
@media (max-width: 640px) {
  .home {
    align-items: flex-start;
    padding: 18px 14px;
  }

  .row {
    flex-wrap: wrap;
    gap: 6px 12px;
    padding: 14px 16px;
  }

  .row__name {
    flex: 1 1 auto;
  }

  .row__blurb {
    flex: 1 1 100%;
    font-size: 12px;
  }
}
</style>