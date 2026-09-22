<script setup lang="ts">
import { useCaseStore } from '@/stores/case'

const store = useCaseStore()

function onText(key: string, event: any) {
  store.setAnswer(key, event.detail.value)
}

function onEnum(key: string, options: string[], event: any) {
  store.setAnswer(key, options[Number(event.detail.value)])
}

function onBool(key: string, event: any) {
  store.setAnswer(key, !!event.detail.value)
}
</script>

<template>
  <view class="form">
    <view class="form__head">
      <text class="form__title">申请信息</text>
      <text class="form__sub">按场景配置自动渲染</text>
    </view>

    <view class="form__body">
      <view v-for="field in store.fields" :key="field.key" class="field">
        <view class="field__top">
          <text class="field__label">
            {{ field.label }}<text v-if="field.required" class="field__req">*</text>
          </text>
          <switch
            v-if="field.type === 'bool'"
            class="field__switch"
            :checked="!!store.answers[field.key]"
            :disabled="store.running"
            color="#1f6feb"
            @change="onBool(field.key, $event)"
          />
        </view>

        <input
          v-if="field.type === 'text'"
          class="field__input"
          :value="store.answers[field.key]"
          :disabled="store.running"
          placeholder="请输入"
          @input="onText(field.key, $event)"
        />

        <input
          v-else-if="field.type === 'number'"
          class="field__input"
          type="number"
          :value="store.answers[field.key]"
          :disabled="store.running"
          placeholder="请输入数字"
          @input="onText(field.key, $event)"
        />

        <picker
          v-else-if="field.type === 'enum'"
          class="field__picker"
          :range="field.options || []"
          :disabled="store.running"
          @change="onEnum(field.key, field.options || [], $event)"
        >
          <view class="field__picker-box">
            <text
              class="field__value"
              :class="{ 'field__value--empty': !store.answers[field.key] }"
            >
              {{ store.answers[field.key] || '请选择' }}
            </text>
            <text class="field__arrow">▾</text>
          </view>
        </picker>
      </view>
    </view>
  </view>
</template>

<style scoped>
.form {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
}

.form__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #eef1f5;
}

.form__title {
  font-size: 15px;
  font-weight: 600;
}

.form__sub {
  font-size: 12px;
  color: #6b7280;
}

.form__body {
  padding: 14px 16px 16px;
}

.field {
  margin-bottom: 14px;
}

.field:last-child {
  margin-bottom: 0;
}

.field__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.field__label {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  line-height: 18px;
  color: #4b5563;
}

.field__req {
  color: #ef4444;
  margin-left: 2px;
}

.field__input {
  width: 100%;
  height: 36px;
  box-sizing: border-box;
  padding: 0 12px;
  font-size: 13px;
  color: #1f2329;
  background: #f7f9fc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.field__picker {
  width: 100%;
}

.field__picker-box {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  box-sizing: border-box;
  padding: 0 12px;
  background: #f7f9fc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
}

.field__value {
  font-size: 13px;
  color: #1f2329;
}

.field__value--empty {
  color: #9aa4b2;
}

.field__arrow {
  font-size: 12px;
  color: #9aa4b2;
}

.field__switch {
  transform: scale(0.86);
}
</style>
