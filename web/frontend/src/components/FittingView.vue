<script setup lang="ts">
import { computed } from 'vue'
import { useFittingStore } from '@/stores/fitting'
import { useBrowserStore } from '@/stores/browser'
import { imageUrl, FittedKind, Item, Module } from '@/api'
import { formatAmount } from '@/format'
import { t } from '@/i18n'

const fitting = useFittingStore()
const browser = useBrowserStore()

const RACK_LABELS: Record<string, string> = {
  high: 'High power',
  med: 'Medium power',
  low: 'Low power',
  rig: 'Rig slot',
  subsystem: 'Subsystem',
  service: 'Service',
  mode: 'Mode',
  system: 'System',
}

const STATE_LABELS: Record<string, string> = {
  offline: 'offline',
  online: 'online',
  active: 'active',
  overheated: 'overheated',
}

function rackCount(rack: string) {
  const slots = fitting.shipSlots
  const key = rack === 'high' ? 'high' : rack === 'med' ? 'med' : rack === 'low' ? 'low' : rack === 'rig' ? 'rig' : rack
  const total = slots[key] ?? 0
  const used = fitting.fit?.racks[rack]?.filter((module) => !module.isEmpty).length ?? 0
  return `${used} / ${total}`
}

function moduleImage(module: Module) {
  return imageUrl(module.item?.image, 1)
}

function selectModule(module: Module) {
  if (module.isEmpty || !module.item) return
  fitting.selectedModule = module.position
  browser.selectItem(module.item, { id: fitting.fit!.id, position: module.position, kind: 'module' })
}

/**
 * Open a row of the fit in the details pane, its own values and all.
 *
 * The fit goes along with the click, which is what makes the pane show what the fit
 * makes of that item rather than the type's base values. ``kind`` is what was clicked:
 * a rack module, or a row of the drone, fighter, cargo, implant or booster list.
 */
function inspect(item: Item, index: number, kind: FittedKind) {
  browser.selectItem(item, { id: fitting.fit!.id, position: index, kind })
}

/** The loaded charge is part of the module's row, and has values of its own. */
function inspectCharge(module: Module) {
  if (!module.charge) return
  fitting.selectedModule = module.position
  browser.selectItem(module.charge.item, {
    id: fitting.fit!.id,
    position: module.position,
    kind: 'moduleCharge',
  })
}

/**
 * A plain click walks the states up and back down again -- online, active, overheated,
 * online -- which is the whole point of the browser's own ``cycle`` click. Ctrl-click
 * takes a module offline and right-click overloads it directly, as on the desktop.
 */
function onStateClick(module: Module, event: MouseEvent) {
  if (module.isEmpty) return
  fitting.cycleModuleState(module, event.ctrlKey ? 'ctrl' : 'cycle')
}

function onStateContext(module: Module, event: MouseEvent) {
  if (module.isEmpty) return
  event.preventDefault()
  fitting.cycleModuleState(module, 'right')
}

/** How many weapons move with this one, itself included (1 when it is on its own). */
function groupSize(module: Module) {
  return 1 + fitting.groupMates(module).length
}

/** "offline — click to cycle, ...", in the language of the moment. */
function stateTitle(module: Module) {
  const state = t(STATE_LABELS[module.state] ?? module.state)
  const title = t('{state} — click to cycle, ctrl-click to offline, right-click to overheat', { state })
  // A grouped weapon moves the whole group, so the tooltip says so before it surprises
  return groupSize(module) > 1 ? title + t(' · the whole weapon group moves together') : title
}

/** Opening the module in the details pane is also how charges get loaded. */
function pickCharge(module: Module) {
  selectModule(module)
}

const containers = computed(() => fitting.fit)
</script>

<template>
  <div v-if="fitting.fit" class="fitting">
    <!-- Racks -->
    <section v-for="rack in fitting.racks" :key="rack.name" class="rack" :class="`slot-${rack.name}`">
      <div class="rackhead">
        <span class="rackname">{{ t(RACK_LABELS[rack.name] ?? rack.name) }}</span>
        <span class="racktail">
          <!-- The one control the desktop has no twin for: it links the weapons of this
               rack, so one state click or one charge reaches all of them -->
          <button
            v-if="rack.name === 'high' && fitting.highWeaponGroups.length"
            class="groupbtn"
            :class="{ active: fitting.weaponGroups }"
            :title="
              t(
                fitting.weaponGroups
                  ? 'Ungroup: every weapon goes back to being on its own'
                  : 'Group the same weapons in this rack so one click or charge reaches them all',
              )
            "
            @click="fitting.toggleWeaponGroups()"
          >
            {{ t(fitting.weaponGroups ? 'ungroup weapons' : 'group weapons') }}
          </button>
          <span class="dim mono">{{ rackCount(rack.name) }}</span>
        </span>
      </div>

      <div v-for="module in rack.modules" :key="module.position" class="module" :class="{ empty: module.isEmpty }">
        <img v-if="moduleImage(module)" :src="moduleImage(module)!" class="icon" alt="" loading="lazy" />
        <span v-else class="icon placeholder" />

        <button class="name" :disabled="module.isEmpty" @click="selectModule(module)">
          {{ module.isEmpty ? '' : module.item?.name }}
          <span v-if="module.isMutated" class="tag">{{ t('mutated') }}</span>
          <span
            v-if="groupSize(module) > 1"
            class="tag group"
            :title="
              t('{count} of the same weapon act together: a state click or a charge reaches them all', {
                count: groupSize(module),
              })
            "
          >
            {{ t('grouped ×{count}', { count: groupSize(module) }) }}
          </span>
        </button>

        <span class="charge">
          <template v-if="module.charge">
            <button
              class="chargebtn"
              :title="t('click to inspect the loaded charge as fitted')"
              @click="inspectCharge(module)"
            >
              {{ module.charge.item.name }}
            </button>
            <span class="dim mono">x{{ module.charge.amount }}</span>
          </template>
          <button v-else-if="!module.isEmpty" class="load" @click="pickCharge(module)">{{ t('load…') }}</button>
        </span>

        <button
          v-if="!module.isEmpty"
          class="state"
          :class="module.state"
          :title="stateTitle(module)"
          @click="onStateClick(module, $event)"
          @contextmenu="onStateContext(module, $event)"
        >
          {{ t(STATE_LABELS[module.state] ?? module.state) }}
        </button>

        <button v-if="!module.isEmpty" class="remove danger" :title="t('Remove')" @click="fitting.removeModule(module)">
          &times;
        </button>
      </div>
    </section>

    <!-- Drones -->
    <section v-if="containers?.drones.length" class="containerblock">
      <div class="rackhead"><span class="rackname">{{ t('Drones') }}</span>
        <span class="dim mono">{{
          t('{active} / {max} active', {
            active: fitting.stats?.resources.drones.active ?? 0,
            max: fitting.stats?.resources.drones.maxActive ?? 0,
          })
        }}</span>
      </div>
      <div v-for="(drone, index) in containers.drones" :key="drone.itemId + '-' + index" class="module">
        <img v-if="drone.item.image" :src="imageUrl(drone.item.image, 1)!" class="icon" alt="" loading="lazy" />
        <button class="name" @click="inspect(drone.item, index, 'drone')">{{ drone.item.name }}</button>
        <span class="charge mono">
          <input
            class="amount"
            type="number"
            min="1"
            :value="drone.amount"
            @change="fitting.setDroneAmount(index, Number(($event.target as HTMLInputElement).value))"
          />
          <span class="dim">{{ t('active {count}', { count: drone.amountActive }) }}</span>
        </span>
        <button class="state" :class="drone.amountActive > 0 ? 'active' : 'offline'" @click="fitting.toggleDrone(index)">
          {{ t(drone.amountActive > 0 ? 'active' : 'idle') }}
        </button>
        <button class="remove danger" :title="t('Remove')" @click="fitting.removeDrone(index)">&times;</button>
      </div>
    </section>

    <!-- Fighters -->
    <section v-if="containers?.fighters.length" class="containerblock">
      <div class="rackhead"><span class="rackname">{{ t('Fighters') }}</span></div>
      <div v-for="(fighter, index) in containers.fighters" :key="fighter.itemId + '-' + index" class="module">
        <img v-if="fighter.item.image" :src="imageUrl(fighter.item.image, 1)!" class="icon" alt="" loading="lazy" />
        <button class="name" @click="inspect(fighter.item, index, 'fighter')">{{ fighter.item.name }}</button>
        <span class="charge mono">{{ fighter.amount }}</span>
        <button class="state" :class="fighter.active ? 'active' : 'offline'">
          {{ t(fighter.active ? 'launched' : 'in bay') }}
        </button>
        <button
          class="remove danger"
          :title="t('Remove')"
          @click="fitting.send('removeLocalFighters', { positions: [index] })"
        >
          &times;
        </button>
      </div>
    </section>

    <!-- Implants -->
    <section v-if="containers?.implants.length" class="containerblock">
      <div class="rackhead">
        <span class="rackname">{{ t('Implants') }}</span>
        <span class="dim">
          {{ t(fitting.fit.implantLocation === 1 ? 'from character' : 'from fit') }}
          <button class="load" @click="fitting.send('changeImplantLocation', { source: fitting.fit.implantLocation === 1 ? 0 : 1 })">
            {{ t('switch') }}
          </button>
        </span>
      </div>
      <div v-for="(implant, index) in containers.implants" :key="implant.itemId + '-' + index" class="module">
        <img v-if="implant.item.image" :src="imageUrl(implant.item.image, 1)!" class="icon" alt="" loading="lazy" />
        <button class="name" @click="inspect(implant.item, index, 'implant')">{{ implant.item.name }}</button>
        <span class="charge" />
        <button class="state" :class="implant.active ? 'active' : 'offline'" @click="fitting.toggleImplant(index)">
          {{ t(implant.active ? 'active' : 'inactive') }}
        </button>
        <button class="remove danger" :title="t('Remove')" @click="fitting.removeImplant(index)">&times;</button>
      </div>
    </section>

    <!-- Boosters -->
    <section v-if="containers?.boosters.length" class="containerblock">
      <div class="rackhead"><span class="rackname">{{ t('Boosters') }}</span></div>
      <div v-for="(booster, index) in containers.boosters" :key="booster.itemId + '-' + index" class="module">
        <img v-if="booster.item.image" :src="imageUrl(booster.item.image, 1)!" class="icon" alt="" loading="lazy" />
        <button class="name" @click="inspect(booster.item, index, 'booster')">{{ booster.item.name }}</button>
        <span class="charge" />
        <button class="state" :class="booster.active ? 'active' : 'offline'" @click="fitting.toggleBooster(index)">
          {{ t(booster.active ? 'active' : 'inactive') }}
        </button>
        <button class="remove danger" :title="t('Remove')" @click="fitting.removeBooster(index)">&times;</button>
      </div>
    </section>

    <!-- Cargo -->
    <section v-if="containers?.cargo.length" class="containerblock">
      <div class="rackhead">
        <span class="rackname">{{ t('Cargo') }}</span>
        <span class="dim mono">
          {{ formatAmount(fitting.stats?.resources.cargo.used, { prec: 3, lowest: 0, highest: 9 }) }}
          / {{ formatAmount(fitting.stats?.resources.cargo.total, { prec: 3, lowest: 0, highest: 9 }) }} m³
        </span>
      </div>
      <div v-for="(cargo, index) in containers.cargo" :key="cargo.itemId" class="module">
        <img v-if="cargo.item.image" :src="imageUrl(cargo.item.image, 1)!" class="icon" alt="" loading="lazy" />
        <button class="name" @click="inspect(cargo.item, index, 'cargo')">{{ cargo.item.name }}</button>
        <span class="charge mono">
          <input
            class="amount"
            type="number"
            min="1"
            :value="cargo.amount"
            @change="fitting.setCargoAmount(cargo.itemId, Number(($event.target as HTMLInputElement).value))"
          />
        </span>
        <span />
        <button class="remove danger" :title="t('Remove')" @click="fitting.removeCargo(cargo.itemId)">&times;</button>
      </div>
    </section>

    <p class="hint dim">
      {{ t('Click an item in the browser below to fit it. Charges go into the selected module. Click a row of the fit to inspect it as fitted.') }}
    </p>
  </div>
</template>

<style scoped>
.fitting {
  padding: 10px 12px 24px;
  display: grid;
  gap: 10px;
}

.rack,
.containerblock {
  border: 1px solid var(--border);
  border-radius: 5px;
  overflow: hidden;
}

.slot-high {
  background: color-mix(in srgb, var(--slot-high) 55%, transparent);
}
.slot-med {
  background: color-mix(in srgb, var(--slot-med) 55%, transparent);
}
.slot-low {
  background: color-mix(in srgb, var(--slot-low) 55%, transparent);
}
.slot-rig {
  background: color-mix(in srgb, var(--slot-rig) 55%, transparent);
}
.slot-subsystem {
  background: color-mix(in srgb, var(--slot-subsystem) 55%, transparent);
}

.containerblock {
  background: var(--bg-panel);
}

.rackhead {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.18);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.rackname {
  color: var(--text-dim);
}

.racktail {
  display: flex;
  gap: 8px;
  align-items: center;
}

.groupbtn {
  font-size: 10px;
  padding: 0 5px;
  text-transform: none;
  letter-spacing: normal;
}

.groupbtn.active {
  color: var(--accent);
  border-color: var(--accent);
}

.tag.group {
  color: var(--accent);
  border-color: var(--accent);
}

.module {
  display: grid;
  grid-template-columns: 30px minmax(140px, 1fr) 150px 92px 26px;
  align-items: center;
  gap: 8px;
  padding: 2px 8px;
  min-height: 30px;
}

.module.empty {
  opacity: 0.5;
}

.module:hover {
  background: rgba(128, 128, 128, 0.09);
}

.icon {
  width: 26px;
  height: 26px;
  object-fit: contain;
}

.icon.placeholder {
  display: inline-block;
}

.name {
  text-align: left;
  background: none;
  border: none;
  padding: 2px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.name:disabled {
  cursor: default;
}

.charge {
  font-size: 12px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  gap: 5px;
  align-items: center;
}

.load {
  font-size: 11px;
  padding: 0 5px;
}

.chargebtn {
  background: none;
  border: none;
  padding: 0;
  font-size: 12px;
  color: inherit;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chargebtn:hover {
  color: var(--accent);
}

.state {
  font-size: 11px;
  padding: 1px 6px;
  text-transform: lowercase;
}

.state.offline {
  color: var(--text-dim);
}

.state.online {
  color: var(--text);
}

.state.active {
  color: var(--ok);
  border-color: var(--ok);
}

.state.overheated {
  color: var(--danger);
  border-color: var(--danger);
}

.amount {
  width: 62px;
  padding: 1px 4px;
}

.remove {
  padding: 0 6px;
  line-height: 1.3;
}

.hint {
  font-size: 12px;
}
</style>
