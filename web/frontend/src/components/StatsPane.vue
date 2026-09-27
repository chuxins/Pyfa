<script setup lang="ts">
import { computed } from 'vue'
import { useFittingStore } from '@/stores/fitting'
import { formatAmount, formatDamageTypes } from '@/format'
import { t } from '@/i18n'

const fitting = useFittingStore()

const stats = computed(() => fitting.stats)

function amount(value: number | null | undefined, prec = 3, lowest = 0, highest = 0) {
  return formatAmount(value ?? 0, { prec, lowest, highest })
}

function percent(value: number | null | undefined) {
  return `${amount(value, 3, 0, 0)}%`
}

/** True when a module in the fit spools up, so the UI can show the range. */
function hasSpool(spooled: { preSpool: { total: number }; fullSpool: { total: number } } | undefined) {
  if (!spooled) return false
  return Math.abs(spooled.preSpool.total - spooled.fullSpool.total) > 1e-6
}

function spoolRange(spooled: { preSpool: { total: number }; fullSpool: { total: number } }) {
  return `${amount(spooled.preSpool.total)}–${amount(spooled.fullSpool.total)}`
}

const errors = computed(() => Object.entries(stats.value?.errors ?? {}))
</script>

<template>
  <div class="stats">
    <div v-if="!stats" class="dim pad">{{ t('No fit open') }}</div>

    <template v-else>
      <!-- Firepower -->
      <section>
        <h3>{{ t('Firepower') }} <span v-if="stats.firepower.hasTargetProfile" class="tag">{{ t('vs target profile') }}</span></h3>
        <div class="row">
          <span>{{ t('Weapon DPS') }}</span>
          <span class="mono">
            {{ formatDamageTypes(stats.firepower.weapon.value) }}
            <span class="dim">= {{ amount(stats.firepower.weapon.value.total) }}</span>
          </span>
        </div>
        <div v-if="hasSpool(stats.firepower.weapon)" class="row sub">
          <span>{{ t('Weapon spool') }}</span><span class="mono">{{ spoolRange(stats.firepower.weapon) }}</span>
        </div>
        <div class="row">
          <span>{{ t('Drone DPS') }}</span>
          <span class="mono">
            {{ formatDamageTypes(stats.firepower.drone.value) }}
            <span class="dim">= {{ amount(stats.firepower.drone.value.total) }}</span>
          </span>
        </div>
        <div class="row strong">
          <span>{{ t('Total DPS') }}</span>
          <span class="mono">{{ amount(stats.firepower.dps.value.total) }}</span>
        </div>
        <div v-if="hasSpool(stats.firepower.dps)" class="row sub">
          <span>{{ t('Total spool') }}</span><span class="mono">{{ spoolRange(stats.firepower.dps) }}</span>
        </div>
        <div class="row">
          <span>{{ t('Total volley') }}</span>
          <span class="mono">{{ amount(stats.firepower.volley.value.total) }}</span>
        </div>
      </section>

      <!-- Capacitor -->
      <section>
        <h3>{{ t('Capacitor') }}</h3>
        <div class="row">
          <span>{{ t('Capacity') }}</span>
          <span class="mono">{{ amount(stats.capacitor.capacity) }} GJ</span>
        </div>
        <div class="row">
          <span>{{ t('Recharge / usage') }}</span>
          <span class="mono dim">+{{ amount(stats.capacitor.recharge) }} / -{{ amount(stats.capacitor.used) }} GJ/s</span>
        </div>
        <div class="row strong">
          <span>{{ t(stats.capacitor.stable ? 'Stable' : 'Lasts') }}</span>
          <span class="mono">
            <template v-if="stats.capacitor.stable">{{ t('yes') }}</template>
            <template v-else>{{ Math.round(stats.capacitor.state) }}s</template>
          </span>
        </div>
        <div class="row">
          <span>{{ t('Delta') }}</span>
          <span class="mono" :class="{ bad: stats.capacitor.delta < 0 }">{{ amount(stats.capacitor.delta, 3, 0, 0) }} GJ/s</span>
        </div>
        <div class="row sub">
          <span>{{ t('Neut resistance') }}</span><span class="mono">{{ percent(stats.capacitor.resistance) }}</span>
        </div>
      </section>

      <!-- Tank -->
      <section>
        <h3>{{ t('Tank') }} <span class="dim">{{ t('hp/s') }}</span></h3>
        <div class="row head">
          <span />
          <span class="dim">{{ t('raw') }}</span>
          <span class="dim">{{ t('effective') }}</span>
        </div>
        <div class="row three">
          <span>{{ t('Passive shield') }}</span>
          <span class="mono">{{ amount(stats.tank.normal.passiveShield) }}</span>
          <span class="mono">{{ amount(stats.tank.effective.passiveShield) }}</span>
        </div>
        <div class="row three">
          <span>{{ t('Shield repair') }}</span>
          <span class="mono">{{ amount(stats.tank.normal.shieldRepair) }}</span>
          <span class="mono">{{ amount(stats.tank.effective.shieldRepair) }}</span>
        </div>
        <div class="row three">
          <span>{{ t('Armor repair') }}</span>
          <span class="mono">{{ amount(stats.tank.normal.armorRepair) }}</span>
          <span class="mono">{{ amount(stats.tank.effective.armorRepair) }}</span>
        </div>
        <div class="row three">
          <span>{{ t('Hull repair') }}</span>
          <span class="mono">{{ amount(stats.tank.normal.hullRepair) }}</span>
          <span class="mono">{{ amount(stats.tank.effective.hullRepair) }}</span>
        </div>
      </section>

      <!-- Resistances and hit points -->
      <section>
        <h3>{{ t('Defence') }}</h3>
        <div class="row head">
          <span />
          <span class="dim">{{ t('EM') }}</span><span class="dim">{{ t('TH') }}</span>
          <span class="dim">{{ t('KIN') }}</span><span class="dim">{{ t('EXP') }}</span>
        </div>
        <div v-for="layer in (['shield', 'armor', 'hull'] as const)" :key="layer" class="row four">
          <span class="cap">{{ t(layer) }}</span>
          <span class="mono">{{ amount(stats.resistances.resistances[layer].em, 3, 0, 0) }}</span>
          <span class="mono">{{ amount(stats.resistances.resistances[layer].thermal, 3, 0, 0) }}</span>
          <span class="mono">{{ amount(stats.resistances.resistances[layer].kinetic, 3, 0, 0) }}</span>
          <span class="mono">{{ amount(stats.resistances.resistances[layer].explosive, 3, 0, 0) }}</span>
        </div>
        <div class="row three">
          <span>{{ t('Hit points') }}</span>
          <span class="mono dim">{{ t('shield') }} {{ amount(stats.resistances.hp.shield, 3, 0, 9) }}</span>
          <span class="mono dim">{{ t('armor') }} {{ amount(stats.resistances.hp.armor, 3, 0, 9) }}</span>
        </div>
        <div class="row three">
          <span />
          <span class="mono dim">{{ t('hull') }} {{ amount(stats.resistances.hp.hull, 3, 0, 9) }}</span>
          <span class="mono">{{ t('total') }} {{ amount(stats.resistances.hp.total, 3, 0, 9) }}</span>
        </div>
        <div class="row strong">
          <span>{{ t('Effective HP') }}</span>
          <span class="mono">{{ amount(stats.resistances.ehp.total, 3, 0, 9) }}</span>
        </div>
        <div v-if="stats.resistances.damagePatternName" class="row sub">
          <span>{{ t('Incoming damage') }}</span><span class="mono">{{ t(stats.resistances.damagePatternName) }}</span>
        </div>
      </section>

      <!-- Resources -->
      <section>
        <h3>{{ t('Resources') }}</h3>
        <div class="row"><span>{{ t('CPU') }}</span><span class="mono">{{ amount(stats.resources.cpu.used, 4, 0, 9) }} / {{ amount(stats.resources.cpu.total, 4, 0, 9) }}</span></div>
        <div class="row"><span>{{ t('Powergrid') }}</span><span class="mono">{{ amount(stats.resources.powergrid.used, 4, 0, 9) }} / {{ amount(stats.resources.powergrid.total, 4, 0, 9) }}</span></div>
        <div class="row"><span>{{ t('Calibration') }}</span><span class="mono">{{ amount(stats.resources.calibration.used, 0, 0, 0) }} / {{ amount(stats.resources.calibration.total, 0, 0, 0) }}</span></div>
        <div class="row"><span>{{ t('Turrets') }}</span><span class="mono">{{ stats.resources.hardpoints.turret.used }} / {{ stats.resources.hardpoints.turret.total }}</span></div>
        <div class="row"><span>{{ t('Launchers') }}</span><span class="mono">{{ stats.resources.hardpoints.launcher.used }} / {{ stats.resources.hardpoints.launcher.total }}</span></div>
        <div class="row"><span>{{ t('Drones') }}</span><span class="mono">{{ stats.resources.drones.active }} / {{ amount(stats.resources.drones.maxActive, 0, 0, 0) }}</span></div>
        <div class="row sub"><span>{{ t('Drone bay') }}</span><span class="mono">{{ amount(stats.resources.drones.bayUsed) }} / {{ amount(stats.resources.drones.bayTotal) }} m³</span></div>
        <div class="row sub"><span>{{ t('Bandwidth') }}</span><span class="mono">{{ amount(stats.resources.drones.bandwidthUsed) }} / {{ amount(stats.resources.drones.bandwidthTotal) }} Mbit/s</span></div>
        <div v-if="stats.resources.fighters.tubesTotal" class="row"><span>{{ t('Fighter tubes') }}</span><span class="mono">{{ stats.resources.fighters.tubesUsed }} / {{ amount(stats.resources.fighters.tubesTotal, 0, 0, 0) }}</span></div>
        <div class="row"><span>{{ t('Cargo') }}</span><span class="mono">{{ amount(stats.resources.cargo.used) }} / {{ amount(stats.resources.cargo.total) }} m³</span></div>
      </section>

      <!-- Targeting and mobility -->
      <section>
        <h3>{{ t('Targeting & misc') }}</h3>
        <div class="row"><span>{{ t('Targets') }}</span><span class="mono">{{ amount(stats.targeting.targets, 0, 0, 0) }}</span></div>
        <div class="row"><span>{{ t('Range') }}</span><span class="mono">{{ amount(stats.targeting.maxTargetRange / 1000) }} km</span></div>
        <div class="row"><span>{{ t('Scan resolution') }}</span><span class="mono">{{ amount(stats.targeting.scanResolution, 3, 0, 0) }} mm</span></div>
        <div class="row"><span>{{ t('Sensor strength') }}</span><span class="mono">{{ amount(stats.targeting.sensorStrength, 3, 0, 0) }} <span class="dim">{{ t(stats.targeting.scanType) }}</span></span></div>
        <div class="row sub"><span>{{ t('Jam chance') }}</span><span class="mono">{{ percent(stats.targeting.jamChance) }}</span></div>
        <div class="row"><span>{{ t('Speed') }}</span><span class="mono">{{ amount(stats.targeting.speed, 3, 0, 0) }} m/s</span></div>
        <div class="row"><span>{{ t('Align time') }}</span><span class="mono">{{ (stats.targeting.alignTime ?? 0).toFixed(2) }} s</span></div>
        <div class="row"><span>{{ t('Signature') }}</span><span class="mono">{{ amount(stats.targeting.signatureRadius, 3, 0, 9) }} m</span></div>
        <div class="row"><span>{{ t('Warp speed') }}</span><span class="mono">{{ (stats.targeting.warpSpeed ?? 0).toFixed(2) }} AU/s</span></div>
        <div class="row sub"><span>{{ t('Probe size') }}</span><span class="mono">{{ amount(stats.targeting.probeSize ?? 0, 3, 0, 0) }}</span></div>
        <div class="row sub"><span>{{ t('Warp core strength') }}</span><span class="mono">{{ amount(stats.targeting.warpCoreStrength, 3, 0, 0) }}</span></div>
        <div class="row sub"><span>{{ t('Mass') }}</span><span class="mono">{{ amount(stats.targeting.mass, 3, 3, 9) }} kg</span></div>
      </section>

      <!-- Remote reps -->
      <section v-if="stats.remoteReps.value.shield || stats.remoteReps.value.armor || stats.remoteReps.value.hull">
        <h3>{{ t('Remote reps') }}</h3>
        <div class="row three head"><span /><span class="dim">{{ t('shield') }}</span><span class="dim">{{ t('armor') }}</span></div>
        <div class="row three">
          <span>{{ t('hp/s') }}</span>
          <span class="mono">{{ amount(stats.remoteReps.value.shield) }}</span>
          <span class="mono">{{ amount(stats.remoteReps.value.armor) }}</span>
        </div>
        <div class="row three">
          <span class="dim">{{ t('hull / cap') }}</span>
          <span class="mono dim">{{ amount(stats.remoteReps.value.hull) }}</span>
          <span class="mono dim">{{ amount(stats.remoteReps.value.capacitor) }} GJ/s</span>
        </div>
      </section>

      <!-- Mining -->
      <section v-if="stats.mining.total.yield">
        <h3>{{ t('Mining') }}</h3>
        <div class="row"><span>{{ t('Total yield') }}</span><span class="mono">{{ amount(stats.mining.total.yield) }} m³/s</span></div>
        <div class="row sub"><span>{{ t('Miner / drone') }}</span><span class="mono">{{ amount(stats.mining.miner.yield) }} / {{ amount(stats.mining.drone.yield) }}</span></div>
      </section>

      <section v-if="errors.length" class="errors">
        <h3>{{ t('Not computed') }}</h3>
        <div v-for="[name, message] in errors" :key="name" class="row">
          <span>{{ name }}</span><span class="mono dim">{{ message }}</span>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.stats {
  padding: 8px 10px 24px;
}

.pad {
  padding: 16px;
}

section {
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}

section:last-child {
  border-bottom: none;
}

h3 {
  margin: 0 0 5px;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-dim);
  display: flex;
  gap: 6px;
  align-items: center;
}

.row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
  padding: 1px 0;
}

.row.three {
  grid-template-columns: 1fr auto auto;
}

.row.four {
  grid-template-columns: 1fr auto auto auto auto;
}

.row.head {
  font-size: 11px;
}

.row.sub {
  font-size: 12px;
  color: var(--text-dim);
}

.row.strong {
  font-weight: 600;
}

.row span:last-child {
  text-align: right;
}

.cap {
  text-transform: capitalize;
}

.bad {
  color: var(--danger);
}

.errors {
  color: var(--danger);
}
</style>
