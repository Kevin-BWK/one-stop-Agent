<script setup lang="ts">
/**
 * 材料提交区（受理之前）。
 *
 * 数据全部来自后端 `/api/materials/*`：清单、槽位、张数上限、核验结果都由服务端给出，
 * 前端只负责渲染与发起"拍照 / 选文件"，新增"一件事"不需要改这个组件。
 *
 * 两种材料形态：
 * - 具名槽位（如身份证的"正面 / 反面"）：一槽一张，缺一不算齐，多传不收；
 * - 多页材料（如多页章程）：不固定页数，受 max_files 约束。
 */
import { computed } from 'vue'

import { useCaseStore } from '@/stores/case'
import type { MaterialFile, MaterialItem } from '@/types/contract'

const store = useCaseStore()

const IMAGE_EXTS = ['jpg', 'jpeg', 'png']

/** 槽位单元格：把"有没有文件、什么状态"摊平成无缺省字段的结构，模板里不用做空判断 */
interface SlotCell {
  slot: string
  state: 'empty' | 'done' | 'fix'
  fileId: string
  url: string
  filename: string
  size: number
  reason: string
  isImage: boolean
  busy: boolean
}

const percent = computed(() =>
  store.materialSummary.total
    ? Math.round((store.materialSummary.passed / store.materialSummary.total) * 100)
    : 0
)

const slotCells = computed<Record<string, SlotCell[]>>(() => {
  const map: Record<string, SlotCell[]> = {}
  store.materials.forEach((material) => {
    if (material.multiple) {
      return
    }
    map[material.id] = material.slots.map((slot) => {
      const done = material.files.find((file) => file.slot === slot && file.status !== '需补正')
      const fix = material.files.find((file) => file.slot === slot && file.status === '需补正')
      const current = done || fix
      return {
        slot,
        state: done ? 'done' : fix ? 'fix' : 'empty',
        fileId: current ? current.file_id : '',
        url: current ? current.url : '',
        filename: current ? current.filename : '',
        size: current ? current.size : 0,
        reason: fix ? fix.reason : '',
        isImage: isImageName(current ? current.filename : ''),
        busy: store.materialBusy === material.id + '|' + slot
      }
    })
  })
  return map
})

function isImageName(name: string): boolean {
  const parts = (name || '').split('.')
  const ext = parts.length > 1 ? parts.pop() || '' : ''
  return IMAGE_EXTS.indexOf(ext.toLowerCase()) >= 0
}

function acceptImage(material: MaterialItem): boolean {
  return material.accept.some((ext) => IMAGE_EXTS.indexOf(String(ext).toLowerCase()) >= 0)
}

/** 多页材料的缩略图卡片 */
function pagesOf(material: MaterialItem): (MaterialFile & { isImage: boolean })[] {
  return material.files.map((file) => ({ ...file, isImage: isImageName(file.filename) }))
}

/**
 * 需补正的文件：说明要完整展示"哪里不对、怎么改"。
 *
 * 后端给的是两句话（问题 + 动作），塞进 84×84 的缩略图里根本显示不出来，
 * 所以在材料条目下单独成块。
 */
function fixNotes(material: MaterialItem): MaterialFile[] {
  return material.files.filter((file) => file.status === '需补正')
}

/** 这张材料"上一次上传被拒"的原因（格式 / 体积这类文件没进来的问题） */
function noticeOf(material: MaterialItem): string {
  const notice = store.materialNotice
  return notice && notice.materialId === material.id ? notice.text : ''
}

/** 空槽位点一下：能拍照就优先调相机，否则走文件选择 */
function onPick(material: MaterialItem, slot: string) {
  if (acceptImage(material)) {
    store.chooseImage(material, slot)
  } else {
    store.chooseFile(material, slot)
  }
}

function sizeText(size: number): string {
  if (size >= 1024 * 1024) {
    return (size / 1024 / 1024).toFixed(1) + ' MB'
  }
  return Math.max(1, Math.round(size / 1024)) + ' KB'
}
</script>

<template>
  <view v-if="store.materials.length" class="panel">
    <view class="panel__head">
      <text class="panel__title">提交材料</text>
      <text class="panel__count">
        已通过 {{ store.materialSummary.passed }}/{{ store.materialSummary.total }}
      </text>
    </view>

    <view class="bar">
      <view class="bar__fill" :style="{ width: percent + '%' }" />
    </view>

    <scroll-view class="panel__body" scroll-y>
      <view v-for="material in store.materials" :key="material.id" class="mat">
        <view class="mat__top">
          <text class="mat__name">{{ material.name }}</text>
          <text
            class="badge"
            :class="{
              'badge--ok': material.status === '已通过',
              'badge--fix': material.status === '需补正'
            }"
          >
            {{ material.status }}
          </text>
        </view>

        <text class="mat__hint">为什么：{{ material.reason }}</text>
        <text class="mat__hint">怎么给：{{ material.form }}</text>

        <!-- 具名槽位：一槽一张 -->
        <view v-if="!material.multiple" class="slots">
          <view v-for="cell in slotCells[material.id]" :key="cell.slot" class="slot">
            <text class="slot__label">{{ cell.slot }}</text>

            <view v-if="cell.state === 'done'" class="slot__box slot__box--ok">
              <image v-if="cell.isImage" class="slot__thumb" :src="cell.url" mode="aspectFill" />
              <view v-else class="slot__doc"><text>PDF</text></view>
              <text class="slot__meta">{{ sizeText(cell.size) }}</text>
              <text class="slot__act" @click="store.removeMaterial(material.id, cell.fileId)">
                撤回
              </text>
            </view>

            <view v-else-if="cell.state === 'fix'" class="slot__box slot__box--fix">
              <image v-if="cell.isImage" class="slot__thumb" :src="cell.url" mode="aspectFill" />
              <view v-else class="slot__doc"><text>PDF</text></view>
              <view class="slot__acts">
                <text class="slot__act slot__act--fix" @click="onPick(material, cell.slot)">重传</text>
                <text class="slot__act" @click="store.removeMaterial(material.id, cell.fileId)">
                  删除
                </text>
              </view>
            </view>

            <view v-else class="slot__box slot__box--empty" @click="onPick(material, cell.slot)">
              <text class="slot__plus">＋</text>
              <text class="slot__cta">{{ cell.busy ? '上传中…' : '上传' + cell.slot }}</text>
            </view>

            <text
              v-if="cell.state === 'empty' && !cell.busy && material.accept.length > 1"
              class="slot__link"
              @click="store.chooseFile(material, cell.slot)"
            >
              从文件中选择
            </text>
          </view>
        </view>

        <!-- 多页材料：不固定页数，受上限约束 -->
        <view v-else class="pages">
          <view
            v-for="file in pagesOf(material)"
            :key="file.file_id"
            class="page"
            :class="{ 'page--fix': file.status === '需补正' }"
          >
            <image v-if="file.isImage" class="page__thumb" :src="file.url" mode="aspectFill" />
            <view v-else class="page__doc"><text>PDF</text></view>
            <text class="page__del" @click="store.removeMaterial(material.id, file.file_id)">×</text>
          </view>

          <view
            v-if="material.files.length < material.max_files"
            class="page page--add"
            @click="onPick(material, '')"
          >
            <text class="slot__plus">＋</text>
            <text class="page__hint">{{ material.files.length }}/{{ material.max_files }}</text>
          </view>
        </view>

        <!-- 上一次上传被拒的原因：格式 / 体积这类"文件没进来"的问题 -->
        <view v-if="noticeOf(material)" class="note note--warn">
          <text class="note__body">{{ noticeOf(material) }}</text>
        </view>

        <!-- 需补正说明：后端给的是一段"哪里不对 + 怎么改"，完整展示 -->
        <view v-for="file in fixNotes(material)" :key="file.file_id" class="note note--fix">
          <text class="note__head">
            {{ file.slot ? '「' + file.slot + '」需要重传' : '这一张需要重传' }}
          </text>
          <text class="note__body">{{ file.reason }}</text>
        </view>

        <text v-if="material.missing_slots.length" class="mat__miss">
          还缺：{{ material.missing_slots.join('、') }}
        </text>
      </view>
    </scroll-view>

    <view class="panel__foot">
      <text v-if="store.materialsReady">材料已齐备，可以开始办理。</text>
      <text v-else>必交材料全部通过后才能开始办理。</text>
    </view>
  </view>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  overflow: hidden;
}

.panel__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 12px 16px 8px;
}

.panel__title {
  font-size: 15px;
  font-weight: 600;
}

.panel__count {
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

.panel__body {
  max-height: 420px;
  padding: 0 16px 8px;
}

.mat {
  padding: 10px 0 12px;
  border-bottom: 1px dashed #f0f2f5;
}

.mat:last-child {
  border-bottom: none;
}

.mat__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.mat__name {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: #1f2329;
}

.badge {
  padding: 1px 8px;
  font-size: 11px;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 999px;
}

.badge--ok {
  color: #15803d;
  background: #e8f6ed;
}

.badge--fix {
  color: #b91c1c;
  background: #fdeaea;
}

.mat__hint {
  display: block;
  margin-top: 3px;
  font-size: 11px;
  line-height: 17px;
  color: #6b7280;
}

.mat__miss {
  display: block;
  margin-top: 6px;
  font-size: 11px;
  color: #b45309;
}

.slots {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}

.slot {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.slot__label {
  font-size: 11px;
  color: #6b7280;
}

.slot__box {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 84px;
  height: 84px;
  box-sizing: border-box;
  padding: 4px;
  border-radius: 10px;
  overflow: hidden;
}

.slot__box--empty {
  border: 1px dashed #c7d0dd;
  background: #fbfcfe;
}

.slot__box--ok {
  border: 1px solid #b7e0c6;
  background: #f4fbf6;
}

.slot__box--fix {
  border: 1px solid #f3b4b4;
  background: #fff7f7;
}

.slot__thumb {
  width: 100%;
  height: 100%;
  border-radius: 8px;
}

.slot__doc {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-size: 12px;
  color: #6b7280;
  background: #eef1f5;
  border-radius: 8px;
}

.slot__plus {
  font-size: 18px;
  color: #9aa4b2;
}

.slot__cta {
  font-size: 11px;
  color: #6b7280;
}

.slot__meta {
  position: absolute;
  bottom: 2px;
  font-size: 10px;
  color: #6b7280;
  background: rgba(255, 255, 255, 0.86);
  border-radius: 6px;
  padding: 0 4px;
}

/* 需补正 / 被拒的说明：整段可读，不再压在缩略图上 */
.note {
  margin-top: 8px;
  padding: 7px 10px;
  border-left: 3px solid #f3b4b4;
  border-radius: 8px;
  background: #fff7f7;
}

.note--warn {
  border-left-color: #f0c674;
  background: #fffbf0;
}

.note__head {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #b91c1c;
}

.note__body {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  line-height: 19px;
  color: #b91c1c;
  word-break: break-word;
}

.note--warn .note__body {
  margin-top: 0;
  color: #92400e;
}

.slot__act,
.slot__link {
  font-size: 11px;
  color: #1f6feb;
}

.slot__acts {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  justify-content: space-around;
  padding: 2px 0;
  background: rgba(255, 255, 255, 0.9);
}

.slot__act--fix {
  color: #b91c1c;
}

.pages {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.page {
  position: relative;
  width: 64px;
  height: 64px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}

.page--fix {
  border-color: #f3b4b4;
}

.page__thumb {
  width: 100%;
  height: 100%;
}

.page__doc {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  font-size: 11px;
  color: #6b7280;
  background: #eef1f5;
}

.page__del {
  position: absolute;
  top: 0;
  right: 2px;
  font-size: 14px;
  color: #b91c1c;
}

.page--add {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-style: dashed;
  border-color: #c7d0dd;
  background: #fbfcfe;
}

.page__hint {
  font-size: 10px;
  color: #9aa4b2;
}

.panel__foot {
  padding: 9px 16px;
  border-top: 1px solid #eef1f5;
  font-size: 12px;
  color: #6b7280;
  background: #fbfcfe;
}
</style>
