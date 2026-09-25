<script setup lang="ts">
/**
 * 办理清单：把"要办哪些事"和"要交哪些材料"各画成一条线性图。
 *
 * 数据来源分两个阶段：
 * - 还没生成材料清单时，用条件判定的**预判**（按已填信息推算，可能变化）；
 * - 生成材料清单之后，用**正式清单**（intake），此时与并联办理一一对应。
 */
import { computed } from 'vue'

import { useCaseStore } from '@/stores/case'
import FlowStrip, { type FlowStep } from './FlowStrip.vue'

const store = useCaseStore()

/**
 * 事项 ID：正式清单 > 条件预判 > 该场景的全部可能事项。
 *
 * 最后这层兜底是为了"一进来就有参考"——还没填信息时，先把该场景
 * 可能涉及的事项摊开给用户看，填完再由条件判定筛成正式清单。
 */
const itemIds = computed(() => {
  if (store.itemIds.length) {
    return store.itemIds
  }
  return store.scenario ? Object.keys(store.scenario.items) : []
})

/** 是否在用"全部可能事项"兜底（此时不是最终清单） */
const usingFallback = computed(() => !store.itemIds.length)

const itemSteps = computed<FlowStep[]>(() =>
  itemIds.value.map((id) => {
    const meta = store.itemsMap[id] || { name: id, department: '', output: '' }
    const status = store.itemStatus[id]
    return {
      key: id,
      title: meta.name,
      subtitle: meta.department + (meta.output ? ' · ' + meta.output : ''),
      badge: status || '待办',
      status: status === '已办结' ? 'done' : status ? 'doing' : 'todo'
    }
  })
)

const itemDone = computed(
  () => itemSteps.value.filter((step) => step.status === 'done').length
)

/** 材料：正式清单按核验状态；预判阶段只有名字，一律标"待提交" */
const materialSteps = computed<FlowStep[]>(() => {
  if (store.materials.length) {
    return store.materials.map((material) => ({
      key: material.id,
      title: material.name,
      subtitle: material.missing_slots.length
        ? '还缺：' + material.missing_slots.join('、')
        : material.form || material.reason,
      badge: material.status,
      status:
        material.status === '已通过' ? 'done' : material.status === '需补正' ? 'warn' : 'todo'
    }))
  }
  return (store.preview ? store.preview.material_names : []).map((name, index) => ({
    key: 'preview-material-' + index,
    title: name,
    subtitle: '待提交',
    badge: '预判',
    status: 'todo' as const
  }))
})

const materialDone = computed(
  () => materialSteps.value.filter((step) => step.status === 'done').length
)

const notes = computed(() => (store.preview ? store.preview.notes : []))
</script>

<template>
  <view class="cl">
    <view class="cl__head">
      <text class="cl__title">办理清单</text>
      <text class="cl__sub">
        {{ store.intakeId ? '正式清单' : '按已填信息预判' }}
      </text>
    </view>

    <view class="cl__block">
      <view class="cl__row">
        <text class="cl__label">需办事项</text>
        <text class="cl__count">共 {{ itemSteps.length }} 项 · 已办结 {{ itemDone }} 项</text>
      </view>
      <text v-if="usingFallback && itemSteps.length" class="cl__tip">
        以下为该场景可能涉及的事项，填完申请信息后会自动筛出你要办的。
      </text>
      <FlowStrip
        :steps="itemSteps"
        direction="vertical"
        empty-text="填好申请信息后，这里会列出要办的事。"
      />
    </view>

    <view class="cl__block">
      <view class="cl__row">
        <text class="cl__label">提交材料</text>
        <text class="cl__count">共 {{ materialSteps.length }} 份 · 已通过 {{ materialDone }} 份</text>
      </view>
      <FlowStrip
        :steps="materialSteps"
        direction="vertical"
        empty-text="生成材料清单后，这里会列出要交的材料。"
      />
    </view>

    <view v-if="notes.length" class="cl__notes">
      <text class="cl__notes-title">为什么多出这几项</text>
      <text v-for="(note, index) in notes" :key="index" class="cl__note">· {{ note }}</text>
    </view>
  </view>
</template>

<style scoped>
.cl {
  padding: 12px 16px 14px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
}

.cl__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}

.cl__title {
  font-size: 15px;
  font-weight: 600;
  color: #1f2329;
}

.cl__sub {
  font-size: 11px;
  color: #9aa4b2;
}

.cl__block + .cl__block {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #f0f2f5;
}

.cl__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 6px;
}

.cl__label {
  font-size: 13px;
  font-weight: 600;
  color: #4b5563;
}

.cl__count {
  font-size: 11px;
  color: #8a94a3;
}

.cl__tip {
  display: block;
  margin-bottom: 6px;
  font-size: 11px;
  line-height: 16px;
  color: #9aa4b2;
}

.cl__notes {
  margin-top: 12px;
  padding: 8px 10px;
  background: #f6f9ff;
  border: 1px solid #dbe6fb;
  border-radius: 8px;
}

.cl__notes-title {
  display: block;
  margin-bottom: 2px;
  font-size: 11px;
  font-weight: 600;
  color: #1f4fa8;
}

.cl__note {
  display: block;
  font-size: 11px;
  line-height: 17px;
  color: #4b5563;
}
</style>
