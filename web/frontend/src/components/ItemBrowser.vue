<script setup lang="ts">
import { computed, ref } from 'vue'
import { useBrowserStore } from '@/stores/browser'
import { useFittingStore } from '@/stores/fitting'
import { imageUrl, Item } from '@/api'
import { t } from '@/i18n'

const browser = useBrowserStore()
const fitting = useFittingStore()
const scope = ref<'market' | 'everything' | 'implants'>('market')

const query = computed({
  get: () => browser.itemQuery,
  set: (value: string) => browser.searchItems(value, scope.value),
})

async function add(item: Item) {
  if (!fitting.fit) return
  await fitting.addItem(item)
  await browser.refreshShipFits()
}

function pick(item: Item) {
  browser.selectItem(item)
}

const KIND_HINT: Record<string, string> = {
  module: 'click to fit into a free slot',
  charge: 'click to load into the selected module',
  drone: 'click to add a stack of 5',
  fighter: 'click to add a squadron',
  implant: 'click to add to implants',
  booster: 'click to add to boosters',
  cargo: 'click to put in the cargo hold',
  ship: 'ships cannot be fitted to a fit',
}
</script>

<template>
  <div class="itembrowser">
    <div class="toolbar">
      <input v-model="query" :placeholder="t('Search items (prefix re: for regex)…')" spellcheck="false" />
      <select v-model="scope" @change="browser.searchItems(browser.itemQuery, scope)">
        <option value="market">{{ t('Market') }}</option>
        <option value="everything">{{ t('Everything') }}</option>
        <option value="implants">{{ t('Implants') }}</option>
      </select>
      <span v-if="browser.itemSearching" class="dim">{{ t('searching…') }}</span>
      <span v-else-if="browser.itemSearchError" class="error">{{ browser.itemSearchError }}</span>
      <span v-else class="dim">{{ t('{count} results', { count: browser.itemResults.length }) }}</span>
    </div>

    <div class="results scroll">
      <div
        v-for="item in browser.itemResults"
        :key="item.id"
        class="result"
        :title="t(KIND_HINT[item.itemKind] ?? '')"
      >
        <button class="pick" @click="pick(item)">
          <img v-if="item.image" :src="imageUrl(item.image, 1)!" alt="" loading="lazy" />
          <span class="name">{{ item.name }}</span>
        </button>
        <span class="dim meta">{{ item.group }}</span>
        <button
          class="add"
          :disabled="!fitting.fit || item.itemKind === 'ship' || fitting.busy"
          @click="add(item)"
        >
          {{ t('add') }}
        </button>
      </div>

      <div v-if="!browser.itemResults.length && !browser.itemSearching" class="dim empty">
        {{ t('Search for a module, charge, drone, implant or booster.') }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.itembrowser {
  display: grid;
  grid-template-rows: auto 1fr;
  height: 100%;
  min-height: 0;
}

.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
}

.toolbar input {
  flex: 0 0 320px;
}

.results {
  padding: 4px 6px 12px;
  min-height: 0;
}

.result {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 160px 54px;
  align-items: center;
  gap: 8px;
  padding: 1px 4px;
  border-radius: 3px;
}

.result:hover {
  background: var(--bg-hover);
}

.pick {
  display: flex;
  align-items: center;
  gap: 7px;
  background: none;
  border: none;
  text-align: left;
  padding: 2px 0;
  overflow: hidden;
}

.pick img {
  width: 22px;
  height: 22px;
  object-fit: contain;
}

.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta {
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.add {
  padding: 0 6px;
  font-size: 11px;
}

.error {
  color: var(--danger);
}

.empty {
  padding: 10px;
  font-size: 12px;
}
</style>
