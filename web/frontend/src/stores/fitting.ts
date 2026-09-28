/**
 * The open fit, and everything that changes it.
 *
 * Every edit is one API call that submits one of pyfa's own commands; the response
 * is the whole refreshed fit plus the undo state, so there is no client-side model
 * of a fit that could drift from the engine's.
 */
import { defineStore } from 'pinia'
import { api, Fit, FitSummary, History, Module } from '@/api'
import { errorText } from '@/errors'
import { t } from '@/i18n'
import { useBrowserStore } from '@/stores/browser'
import { useSessionStore } from '@/stores/session'

const RACK_ORDER = ['high', 'med', 'low', 'rig', 'subsystem', 'service', 'mode', 'system'] as const

/**
 * The fit the browser was last on, so opening the site lands in the assembly page of that
 * fit instead of an empty frame. A browser-side convenience only: the server keeps no
 * record of what a pilot looked at last.
 */
const LAST_FIT_KEY = 'pyfa.lastFit'

function rememberFit(fitId: number) {
  try {
    window.localStorage.setItem(LAST_FIT_KEY, String(fitId))
  } catch {
    // Private mode, or storage turned off: the fit is remembered for this page only
  }
}

function rememberedFit(): number | null {
  try {
    const stored = window.localStorage.getItem(LAST_FIT_KEY)
    const fitId = stored === null ? Number.NaN : Number(stored)
    return Number.isInteger(fitId) ? fitId : null
  } catch {
    return null
  }
}

export const useFittingStore = defineStore('fitting', {
  state: () => ({
    fit: null as Fit | null,
    history: { canUndo: false, canRedo: false, depth: 0, undoName: null, redoName: null } as History,
    loading: false,
    busy: false,
    error: '' as string,
    notice: '' as string,
    selectedModule: null as number | null,
    /**
     * The high rack's weapon grouping: the same weapon there acts as one unit, so a state
     * click or a loaded charge reaches every weapon in the group. A browser-only idea (the
     * engine has no weapon groups); it is per open fit and never saved.
     */
    weaponGroups: false as boolean,
    //: Set right after a local edit so our own SSE echo does not reload twice
    quietUntil: 0,
    stream: null as EventSource | null,
  }),

  getters: {
    racks(state): { name: string; modules: NonNullable<Fit['racks'][string]> }[] {
      if (!state.fit) return []
      return RACK_ORDER.map((name) => ({ name, modules: state.fit!.racks[name] ?? [] })).filter(
        (rack) => rack.modules.length > 0,
      )
    },
    shipSlots(state): Record<string, number> {
      return state.fit?.ship?.slots ?? {}
    },
    stats(state) {
      return state.fit?.stats ?? null
    },
    /**
     * The weapons of the high rack that have a twin there, by type id. Grouping links
     * these and nothing else: two different weapons in the same rack stay on their own,
     * which is what EVE's weapon groups do as well.
     */
    highWeaponGroups(state): { itemId: number; positions: number[] }[] {
      const byType = new Map<number, number[]>()
      for (const module of state.fit?.racks.high ?? []) {
        if (module.isEmpty || !module.hardpoint || module.itemId === null) continue
        const positions = byType.get(module.itemId) ?? []
        positions.push(module.position)
        byType.set(module.itemId, positions)
      }
      return [...byType.entries()]
        .filter(([, positions]) => positions.length > 1)
        .map(([itemId, positions]) => ({ itemId, positions }))
    },

    /**
     * The rack module the details pane is talking to, when the click was on one. The
     * charge list uses it to mark the charge that module already has loaded, which is
     * where a different ammunition is picked.
     */
    selectedRackModule(state): Module | null {
      if (state.selectedModule === null || !state.fit) return null
      for (const name of RACK_ORDER) {
        const module = (state.fit.racks[name] ?? []).find((entry) => entry.position === state.selectedModule)
        if (module) return module
      }
      return null
    },
  },

  actions: {
    setError(error: unknown) {
      // A refusal carries a code and its values, so the banner can be in the
      // reader's language rather than the server's (see @/errors)
      this.error = errorText(error)
      window.setTimeout(() => {
        if (this.error) this.error = ''
      }, 6000)
    },

    async open(fitId: number) {
      this.loading = true
      try {
        const fit = await api.fit(fitId)
        this.applyFit(fit)
        this.selectedModule = null
        this.weaponGroups = false
        rememberFit(fitId)
      } catch (error) {
        this.setError(error)
      } finally {
        this.loading = false
      }
    },

    applyFit(fit: Fit) {
      this.fit = fit
      if (fit.history) this.history = fit.history
      this.quietUntil = Date.now() + 1500
    },

    /**
     * Open the fit the browser was last on, so the site comes up on an assembly page
     * rather than an empty frame.
     *
     * The remembered fit wins as long as it is still in the list; failing that -- a first
     * visit, another browser, or a fit deleted since -- the most recently changed one
     * does, since `/api/fits` arrives newest first. Read the list first so a fit that is
     * gone is not opened at all: `open` would show the 404 as an error banner.
     */
    async openLast() {
      if (this.fit) return
      let fits: FitSummary[]
      try {
        ;({ fits } = await api.fits())
      } catch (error) {
        this.setError(error)
        return
      }
      const remembered = rememberedFit()
      const chosen = fits.find((entry) => entry.id === remembered) ?? fits[0]
      if (chosen) await this.open(chosen.id)
    },

    async reload() {
      if (!this.fit) return
      const fit = await api.fit(this.fit.id)
      this.applyFit(fit)
    },

    async refreshStats() {
      if (!this.fit) return
      const { stats } = await api.stats(this.fit.id)
      if (this.fit) this.fit.stats = stats
    },

    async create(shipId: number, name?: string) {
      this.busy = true
      try {
        const fit = await api.createFit(shipId, name)
        this.applyFit(fit)
        this.weaponGroups = false
        await this.reload()
        return fit.id
      } catch (error) {
        this.setError(error)
        return null
      } finally {
        this.busy = false
      }
    },

    async send(command: string, args: Record<string, unknown> = {}) {
      if (!this.fit) return null
      this.busy = true
      try {
        const fit = await api.runCommand(this.fit.id, command, args)
        this.applyFit(fit)
        return fit
      } catch (error) {
        this.setError(error)
        return null
      } finally {
        this.busy = false
      }
    },

    async undo() {
      if (!this.fit) return
      this.busy = true
      try {
        this.applyFit(await api.undo(this.fit.id))
      } catch (error) {
        this.setError(error)
      } finally {
        this.busy = false
      }
    },

    async redo() {
      if (!this.fit) return
      this.busy = true
      try {
        this.applyFit(await api.redo(this.fit.id))
      } catch (error) {
        this.setError(error)
      } finally {
        this.busy = false
      }
    },

    async reset() {
      if (!this.fit) return
      this.busy = true
      try {
        await api.resetFit(this.fit.id)
        await this.reload()
        const history = await api.history(this.fit.id)
        this.history = history
        this.notice = 'Fit cleared'
      } catch (error) {
        this.setError(error)
      } finally {
        this.busy = false
        window.setTimeout(() => (this.notice = ''), 2500)
      }
    },

    async rename(name: string) {
      await this.send('renameFit', { name })
    },

    async remove() {
      if (!this.fit) return null
      const fitId = this.fit.id
      try {
        await api.deleteFit(fitId)
        this.fit = null
        return fitId
      } catch (error) {
        this.setError(error)
        return null
      }
    },

    async addItem(item: { id: number; itemKind: string }) {
      if (!this.fit) return this.promptForMissingFit()
      switch (item.itemKind) {
        case 'module':
          return this.send('addLocalModule', { itemId: item.id })
        case 'drone':
          return this.send('addLocalDrone', { itemId: item.id, amount: 5 })
        case 'fighter':
          return this.send('addLocalFighter', { itemId: item.id })
        case 'implant':
          return this.send('addImplant', { itemId: item.id })
        case 'booster':
          return this.send('addBooster', { itemId: item.id })
        case 'charge':
          return this.loadCharge(item.id)
        default:
          return this.send('addCargo', { itemId: item.id, amount: 1 })
      }
    },

    /**
     * A write with no fit open, from a pane that can be reached without one: the item
     * browser's details pane draws signed out, so its "add" and "load" buttons are live
     * with nothing to write to.
     *
     * Nobody signed in is why there is no fit, so ask for the login; a pilot who is signed
     * in with nothing open gets the same silence those buttons have always given.
     */
    promptForMissingFit() {
      const session = useSessionStore()
      if (!session.signedIn) session.promptLogin()
      return null
    },

    /** Load a charge into the selected module, or every module that accepts it. */
    async loadCharge(chargeItemId: number) {
      if (!this.fit) return this.promptForMissingFit()
      if (this.selectedModule !== null) {
        // The selected module, plus the weapons it is grouped with: a weapon group shares
        // its ammunition, which is half of what grouping is for
        const selected = this.moduleAt(this.selectedModule)
        const positions = selected
          ? [selected.position, ...this.groupMates(selected)]
          : [this.selectedModule]
        const result = await this.send('changeLocalModuleCharges', { positions, chargeItemId })
        if (result) {
          if (positions.length > 1) this.showNotice(t('Loaded into {count} modules', { count: positions.length }))
          return result
        }
      }
      const { targets } = await api.chargeTargets(this.fit.id, chargeItemId)
      if (!targets.length) {
        this.setError(new Error(t('No fitted module can load this charge')))
        return null
      }
      if (targets.length === 1) {
        return this.send('changeLocalModuleCharges', {
          positions: [targets[0].position],
          chargeItemId,
        })
      }
      // Several candidates: match by type id, which is what the desktop does
      const positions = targets.map((target) => target.position)
      const result = await this.send('changeLocalModuleCharges', { positions, chargeItemId })
      if (result) this.showNotice(t('Loaded into {count} modules', { count: positions.length }))
      return result
    },

    /** The module at a position; positions are indices into the fit's module list. */
    moduleAt(position: number): Module | null {
      for (const modules of Object.values(this.fit?.racks ?? {})) {
        const found = (modules ?? []).find((module) => module.position === position)
        if (found) return found
      }
      return null
    },

    /** The other weapons that move with this one, when grouping is on and it has a twin. */
    groupMates(module: { position: number; itemId?: number | null }): number[] {
      if (!this.weaponGroups || module.itemId === null || module.itemId === undefined) return []
      const group = this.highWeaponGroups.find((entry) => entry.itemId === module.itemId)
      if (!group) return []
      return group.positions.filter((position) => position !== module.position)
    },

    toggleWeaponGroups() {
      this.weaponGroups = !this.weaponGroups
    },

    showNotice(text: string) {
      this.notice = text
      window.setTimeout(() => {
        if (this.notice === text) this.notice = ''
      }, 2500)
    },

    async cycleModuleState(
      module: { position: number; itemId: number | null },
      click: 'cycle' | 'left' | 'right' | 'ctrl',
    ) {
      return this.send('changeLocalModuleStates', {
        main: { kind: 'module', position: module.position },
        // Grouped weapons move together, the way a desktop multi-selection does: the
        // engine is handed the clicked module and the rest of its group
        positions: this.groupMates(module),
        click,
      })
    },

    async removeModule(module: { position: number }) {
      return this.send('removeLocalModules', { positions: [module.position] })
    },

    async setDroneAmount(position: number, amount: number) {
      return this.send('changeLocalDroneAmount', { position, amount })
    },

    async toggleDrone(position: number) {
      return this.send('toggleLocalDroneStates', { main: { kind: 'drone', position } })
    },

    async removeDrone(position: number) {
      return this.send('removeLocalDrones', { positions: [position] })
    },

    async removeCargo(itemId: number) {
      return this.send('removeCargos', { itemIds: [itemId] })
    },

    async setCargoAmount(itemId: number, amount: number) {
      return this.send('changeCargosAmount', { itemIds: [itemId], amount })
    },

    async toggleImplant(position: number) {
      return this.send('toggleImplantStates', { main: { kind: 'implant', position } })
    },

    async removeImplant(position: number) {
      return this.send('removeImplants', { positions: [position] })
    },

    async toggleBooster(position: number) {
      return this.send('toggleBoosterStates', { main: { kind: 'booster', position } })
    },

    async removeBooster(position: number) {
      return this.send('removeBoosters', { positions: [position] })
    },

    /** Live updates: another tab editing the same fit refreshes this one. */
    connect() {
      if (this.stream) return
      this.stream = new EventSource('/api/events')
      this.stream.addEventListener('fit.changed', (event) => {
        const payload = JSON.parse((event as MessageEvent).data)
        if (!this.fit) return
        if (Array.isArray(payload.fitIds) && payload.fitIds.includes(this.fit.id)) {
          if (Date.now() < this.quietUntil) return
          this.refreshStats()
        }
      })
      // An import adds fits to ships, so the tree's counts and the open ship's list are
      // both out of date -- including for the tab that did the import, which refreshes
      // itself and sets `quietUntil` so this does not repeat its queries.
      this.stream.addEventListener('fits.imported', () => {
        const browser = useBrowserStore()
        if (Date.now() < browser.quietUntil) return
        void browser.refreshFits()
      })
      this.stream.addEventListener('fit.renamed', (event) => {
        const payload = JSON.parse((event as MessageEvent).data)
        if (this.fit) this.refreshStats()
        if (typeof payload.fitId === 'number') useBrowserStore().invalidateFit(payload.fitId)
      })
      this.stream.addEventListener('fit.removed', (event) => {
        const payload = JSON.parse((event as MessageEvent).data)
        if (this.fit && Array.isArray(payload.fitIds) && payload.fitIds.includes(this.fit.id)) {
          this.fit = null
          this.notice = t('This fit was deleted')
        }
        for (const fitId of payload.fitIds ?? []) useBrowserStore().invalidateFit(fitId)
      })
    },

    disconnect() {
      this.stream?.close()
      this.stream = null
    },
  },
})
