<script setup lang="ts">
import { computed, ref } from 'vue'
import { useBrowserStore } from '@/stores/browser'
import { useFittingStore } from '@/stores/fitting'
import { imageUrl } from '@/api'
import { formatAmount } from '@/format'
import { t } from '@/i18n'

const browser = useBrowserStore()
const fitting = useFittingStore()

const emit = defineEmits<{ close: [] }>()

const onlyChanged = ref(false)
const tab = ref<'attributes' | 'charges' | 'variations' | 'skills'>('attributes')

const item = computed(() => browser.selectedItem)

const attributes = computed(() => {
  if (!onlyChanged.value || !browser.selectedAttributesModified) return browser.selectedAttributes
  return browser.selectedAttributes.filter(
    (row) => row.baseValue === undefined || row.baseValue === null || Math.abs(row.baseValue - row.value) > 1e-9,
  )
})

function number(value: number | null | undefined) {
  if (value === null || value === undefined) return '–'
  if (Number.isInteger(value)) return String(value)
  return formatAmount(value, { prec: 5, lowest: 0, highest: 9 })
}

async function loadCharge(chargeId: number) {
  await fitting.loadCharge(chargeId)
  await browser.refreshShipFits()
}

async function addAsItem(itemId: number, kind: string) {
  await fitting.addItem({ id: itemId, itemKind: kind })
  await browser.refreshShipFits()
}

const canAdd = computed(() => {
  const kind = item.value?.itemKind
  return kind && kind !== 'ship' && kind !== 'charge'
})
</script>

<template>
  <div v-if="item" class="details">
    <div class="head">
      <img v-if="item.image" :src="imageUrl(item.image, 2)!" alt="" />
      <div class="titles">
        <div class="name">{{ item.name }}</div>
        <div class="dim">{{ item.category }} <span v-if="item.group">· {{ item.group }}</span>
          <span v-if="item.metaGroup"> · {{ item.metaGroup }}</span>
        </div>
      </div>
      <button class="close" @click="emit('close')">&times;</button>
    </div>

    <div class="actions">
      <button
        v-if="canAdd"
        class="primary"
        :disabled="fitting.busy"
        @click="addAsItem(item.id, item.itemKind)"
      >
        {{ t('Add to fit') }}
      </button>
    </div>

    <nav class="tabs">
      <button :class="{ active: tab === 'attributes' }" @click="tab = 'attributes'">{{ t('Attributes') }}</button>
      <button :class="{ active: tab === 'charges' }" @click="tab = 'charges'">
        {{ t('Charges ({count})', { count: browser.selectedCharges.length }) }}
      </button>
      <button :class="{ active: tab === 'variations' }" @click="tab = 'variations'">
        {{ t('Variants ({count})', { count: browser.selectedVariations.length }) }}
      </button>
      <button :class="{ active: tab === 'skills' }" @click="tab = 'skills'">
        {{ t('Skills ({count})', { count: browser.selectedRequirements.length }) }}
      </button>
    </nav>

    <div class="body scroll">
      <template v-if="tab === 'attributes'">
        <label v-if="browser.selectedAttributesModified" class="toggle">
          <input v-model="onlyChanged" type="checkbox" /> {{ t('only attributes changed by the fit') }}
        </label>
        <div v-for="row in attributes" :key="row.name" class="attr" :title="row.description ?? ''">
          <span class="attrname">{{ row.displayName }}</span>
          <span class="mono">
            {{ number(row.value) }}
            <span v-if="row.unit" class="dim">{{ row.unit }}</span>
            <span v-if="row.baseValue != null && Math.abs(row.baseValue - row.value) > 1e-9" class="dim base">
              {{ t('(base {value})', { value: number(row.baseValue) }) }}
            </span>
          </span>
        </div>
        <div v-if="!attributes.length" class="dim pad">{{ t('No published attributes.') }}</div>
      </template>

      <template v-else-if="tab === 'charges'">
        <div v-for="charge in browser.selectedCharges" :key="charge.id" class="line">
          <button class="linkish" @click="browser.selectItem(charge)">{{ charge.name }}</button>
          <button class="addsmall" :disabled="!fitting.fit || fitting.busy" @click="loadCharge(charge.id)">{{ t('load') }}</button>
        </div>
        <div v-if="!browser.selectedCharges.length" class="dim pad">{{ t('This item takes no charges.') }}</div>
      </template>

      <template v-else-if="tab === 'variations'">
        <div v-for="variation in browser.selectedVariations" :key="variation.id" class="line">
          <button class="linkish" @click="browser.selectItem(variation)">{{ variation.name }}</button>
          <span class="dim">{{ variation.metaGroup }}</span>
        </div>
        <div v-if="!browser.selectedVariations.length" class="dim pad">{{ t('No variants.') }}</div>
      </template>

      <template v-else>
        <div v-for="skill in browser.selectedRequirements" :key="skill.skillId" class="line">
          <span>{{ skill.name }}</span>
          <span class="mono dim">{{ t('level {level}', { level: skill.level }) }}</span>
        </div>
        <div v-if="!browser.selectedRequirements.length" class="dim pad">{{ t('No skill requirements.') }}</div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.details {
  display: grid;
  grid-template-rows: auto auto auto 1fr;
  height: 100%;
  min-height: 0;
}

.head {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 9px 10px;
  border-bottom: 1px solid var(--border);
}

.head img {
  width: 52px;
  height: 52px;
  object-fit: contain;
}

.titles {
  flex: 1;
  min-width: 0;
}

.name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
}

.close {
  padding: 0 7px;
}

.actions {
  display: flex;
  gap: 6px;
  padding: 7px 10px;
  flex-wrap: wrap;
}

.tabs {
  display: flex;
  gap: 2px;
  padding: 0 8px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.tabs button {
  border: none;
  border-bottom: 2px solid transparent;
  background: none;
  border-radius: 0;
  padding: 5px 8px;
  font-size: 12px;
  color: var(--text-dim);
}

.tabs button.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}

.body {
  padding: 6px 10px 20px;
  min-height: 0;
}

.toggle {
  display: block;
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 4px;
}

.attr {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 1px 0;
  border-bottom: 1px dotted var(--border);
}

.attrname {
  overflow: hidden;
  text-overflow: ellipsis;
}

.base {
  font-size: 11px;
}

.line {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  padding: 2px 0;
  border-bottom: 1px dotted var(--border);
}

.linkish {
  background: none;
  border: none;
  text-align: left;
  padding: 2px 0;
  color: var(--accent);
}

.addsmall {
  font-size: 11px;
  padding: 0 6px;
}

.pad {
  padding: 10px 2px;
}
</style>
