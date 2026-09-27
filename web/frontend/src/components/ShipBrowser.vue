<script setup lang="ts">
import { computed } from 'vue'
import { useBrowserStore } from '@/stores/browser'
import { useFittingStore } from '@/stores/fitting'
import { imageUrl } from '@/api'
import { t } from '@/i18n'

const browser = useBrowserStore()
const fitting = useFittingStore()

const shipQuery = computed({
  get: () => browser.shipFilter,
  set: (value: string) => browser.searchShips(value),
})

async function openFit(fitId: number) {
  await fitting.open(fitId)
}

async function newFit() {
  if (browser.shipId === null) return
  const fitId = await fitting.create(browser.shipId)
  if (fitId !== null) browser.noteFitAdded(browser.shipId)
}

function renderUrl(ship: { image?: { kind: string; id: number } | null }) {
  return imageUrl(ship.image as any, 1)
}
</script>

<template>
  <div class="browser">
    <div class="search">
      <input v-model="shipQuery" :placeholder="t('Search ships…')" spellcheck="false" />
    </div>

    <button class="esi" :disabled="browser.importing" @click="browser.importFromEsi()">
      {{ browser.importing ? t('importing…') : t('Import my EVE fits') }}
    </button>

    <div class="scroll tree">
      <!-- Search results replace the tree while a query is active -->
      <template v-if="browser.shipSearchResults">
        <div class="header">{{ t('Results ({count})', { count: browser.shipSearchResults.length }) }}</div>
        <template v-for="ship in browser.shipSearchResults" :key="ship.id">
          <button
            class="shiprow"
            :class="{ selected: ship.id === browser.shipId }"
            @click="browser.selectShip(ship.id)"
          >
            <img v-if="renderUrl(ship)" :src="renderUrl(ship)!" alt="" loading="lazy" />
            <span>{{ ship.name }}</span>
          </button>
        </template>
      </template>

      <template v-else>
        <template v-for="category in browser.categories" :key="category.key">
          <button class="header toggle" @click="browser.toggleCategory(category.key)">
            {{ browser.collapsedCategories[category.key] ? '▸' : '▾' }} {{ category.name }}
          </button>
          <template v-if="!browser.collapsedCategories[category.key]">
            <template v-for="group in category.groups" :key="group.id">
              <button
                class="group toggle"
                @click="browser.toggleGroup(category.key, group.name)"
              >
                {{ browser.collapsedGroups[`${category.key}/${group.name}`] ? '▸' : '▾' }}
                {{ group.name }}
                <span class="dim">{{ group.ships.length }}</span>
              </button>
              <template v-if="!browser.collapsedGroups[`${category.key}/${group.name}`]">
                <template v-for="ship in group.ships" :key="ship.id">
                  <button
                    class="shiprow"
                    :class="{ selected: ship.id === browser.shipId }"
                    @click="browser.selectShip(ship.id)"
                  >
                    <!-- The caret is its own click target: showing the fits should not
                         also open the ship's detail pane -->
                    <span
                      v-if="ship.fitCount"
                      class="caret"
                      :title="t('Show the fits saved for this ship')"
                      @click.stop="browser.toggleShipFits(ship.id)"
                    >{{ browser.expandedShips[ship.id] ? '▾' : '▸' }}</span>
                    <span v-else class="caret blank"></span>
                    <img v-if="renderUrl(ship)" :src="renderUrl(ship)!" alt="" loading="lazy" />
                    <span class="shipname">{{ ship.name }}</span>
                    <span v-if="ship.fitCount" class="dim count">{{ ship.fitCount }}</span>
                  </button>
                  <template v-if="ship.fitCount && browser.expandedShips[ship.id]">
                    <div v-if="browser.loadingFits[ship.id]" class="dim nested">
                      {{ t('reading fits…') }}
                    </div>
                    <button
                      v-for="fit in browser.shipFitsById[ship.id] ?? []"
                      :key="fit.id"
                      class="fitrow nested"
                      :class="{ selected: fitting.fit?.id === fit.id }"
                      @click="openFit(fit.id)"
                    >
                      <span class="fitname">{{ fit.name }}</span>
                      <span v-if="fit.booster" class="tag">{{ t('booster') }}</span>
                    </button>
                  </template>
                </template>
              </template>
            </template>
          </template>
        </template>
      </template>
    </div>

    <div v-if="browser.ship" class="shipdetail">
      <div class="shiphead">
        <img v-if="renderUrl(browser.ship)" :src="renderUrl(browser.ship)!" alt="" />
        <div>
          <div class="shipname">{{ browser.ship.name }}</div>
          <div class="dim slots">
            <span>{{ t('hi') }} {{ browser.shipSlots.high }}</span>
            <span>{{ t('med') }} {{ browser.shipSlots.med }}</span>
            <span>{{ t('low') }} {{ browser.shipSlots.low }}</span>
            <span>{{ t('rig') }} {{ browser.shipSlots.rig }}</span>
            <span v-if="browser.shipSlots.subsystem">{{ t('sub') }} {{ browser.shipSlots.subsystem }}</span>
          </div>
        </div>
      </div>

      <button class="primary newfit" :disabled="fitting.busy" @click="newFit">+ {{ t('New fit') }}</button>

      <div class="fits scroll">
        <div v-if="!browser.shipFits.length" class="dim empty">{{ t('No saved fits yet') }}</div>
        <button
          v-for="fit in browser.shipFits"
          :key="fit.id"
          class="fitrow"
          :class="{ selected: fitting.fit?.id === fit.id }"
          @click="openFit(fit.id)"
        >
          <span class="fitname">{{ fit.name }}</span>
          <span v-if="fit.booster" class="tag">{{ t('booster') }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.browser {
  display: grid;
  grid-template-rows: auto auto 1fr auto;
  height: 100%;
  min-height: 0;
}

.search {
  padding: 8px;
}

.search input {
  width: 100%;
}

.esi {
  margin: 0 8px 6px;
}

.tree {
  padding: 0 4px;
  min-height: 0;
}

.header {
  width: 100%;
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-dim);
  background: none;
  border: none;
  padding: 6px 6px 3px;
}

.toggle {
  cursor: pointer;
}

.group {
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  padding: 3px 6px 3px 16px;
  color: var(--text);
  display: flex;
  justify-content: space-between;
}

.group:hover {
  background: var(--bg-hover);
}

.shiprow {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 6px;
  text-align: left;
  background: none;
  border: none;
  padding: 2px 6px 2px 16px;
  border-radius: 3px;
}

.caret {
  width: 10px;
  color: var(--text-dim);
  font-size: 10px;
}

.caret.blank {
  display: inline-block;
}

.shiprow img {
  width: 24px;
  height: 24px;
  object-fit: contain;
}

.shipname {
  flex: 1;
}

.count {
  font-size: 11px;
}

.shiprow:hover {
  background: var(--bg-hover);
}

.shiprow.selected {
  background: var(--accent-dim);
}

.shipdetail {
  border-top: 1px solid var(--border);
  padding: 8px;
  display: grid;
  gap: 6px;
  max-height: 45%;
  grid-template-rows: auto auto 1fr;
}

.shiphead {
  display: flex;
  gap: 8px;
  align-items: center;
}

.shiphead img {
  width: 44px;
  height: 44px;
  object-fit: contain;
}

.shipname {
  font-weight: 600;
}

.slots {
  display: flex;
  gap: 7px;
  font-size: 11px;
}

.newfit {
  width: 100%;
}

.fits {
  display: grid;
  gap: 2px;
  align-content: start;
  min-height: 60px;
}

.fitrow {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  text-align: left;
  background: none;
  border: none;
  padding: 3px 6px;
}

.fitrow.nested {
  padding-left: 42px;
  color: var(--text-dim);
}

.nested {
  padding-left: 42px;
}

.fitrow:hover {
  background: var(--bg-hover);
}

.fitrow.selected {
  background: var(--accent-dim);
}

.empty {
  padding: 6px;
  font-size: 12px;
}
</style>
