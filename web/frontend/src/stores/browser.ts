/**
 * Ship browser and item search state.
 */
import { defineStore } from 'pinia'
import { api, AttributeRow, EsiImportResult, FittedKind, FitSummary, Item, ShipCategory, ShipSummary } from '@/api'
import { errorText } from '@/errors'
import { t } from '@/i18n'

/** The tree row of one ship, so a single badge can be updated without re-reading the tree. */
function findShip(categories: ShipCategory[], shipId: number): ShipSummary | null {
  for (const category of categories) {
    for (const group of category.groups) {
      const ship = group.ships.find((entry) => entry.id === shipId)
      if (ship) return ship
    }
  }
  return null
}

/** What to say after an import: what arrived, and why the rest did not. */
function importNotice(result: EsiImportResult): string {
  const skipped: Record<string, number> = {}
  for (const entry of result.skipped) skipped[entry.reason] = (skipped[entry.reason] ?? 0) + 1

  const parts: string[] = []
  if (result.imported.length) {
    parts.push(
      t('Imported {count} fits from {name}', {
        count: result.imported.length,
        name: result.character.name,
      }),
    )
  }
  if (skipped.alreadyImported) {
    parts.push(t('{count} were already in pyfa', { count: skipped.alreadyImported }))
  }
  if (skipped.unknownShip) {
    parts.push(
      t('{count} are for ships this game data does not know', { count: skipped.unknownShip }),
    )
  }
  if (skipped.unreadable) {
    parts.push(t('{count} could not be read', { count: skipped.unreadable }))
  }
  if (!parts.length) return t('EVE has no fitting saved for {name}', { name: result.character.name })
  return parts.join('; ')
}

export const useBrowserStore = defineStore('browser', {
  state: () => ({
    categories: [] as ShipCategory[],
    treeLoaded: false,
    collapsedCategories: {} as Record<string, boolean>,
    collapsedGroups: {} as Record<string, boolean>,
    shipFilter: '',

    shipId: null as number | null,
    ship: null as ShipSummary | null,
    shipSlots: {} as Record<string, number>,
    shipLoading: false,
    shipSearchResults: null as ShipSummary[] | null,

    /** Ships showing their fits under them in the tree */
    expandedShips: {} as Record<number, boolean>,
    /** ship id -> its fits; an absent entry means "not read yet" */
    shipFitsById: {} as Record<number, FitSummary[]>,
    loadingFits: {} as Record<number, boolean>,

    importing: false,
    error: '' as string,
    notice: '' as string,
    /** Set right after a local import, so our own SSE echo does not fetch twice */
    quietUntil: 0,

    itemQuery: '',
    itemScope: 'market' as 'market' | 'everything' | 'implants',
    itemResults: [] as Item[],
    itemSearching: false,
    itemSearchError: '',

    selectedItem: null as Item | null,
    selectedAttributes: [] as AttributeRow[],
    selectedAttributesModified: false,
    selectedCharges: [] as Item[],
    selectedVariations: [] as Item[],
    selectedRequirements: [] as { skillId: number; name: string; level: number }[],
    detailLoading: false,
  }),

  getters: {
    /** The fits shown under the selected ship, read from the same list the tree shows. */
    shipFits(state): FitSummary[] {
      if (state.shipId === null) return []
      return state.shipFitsById[state.shipId] ?? []
    },
  },

  actions: {
    applyTree(categories: ShipCategory[]) {
      this.categories = categories
      // Frigates first is friendlier than an alphabetical dump. Keys are the English
      // category names: `name` follows the server's language, `key` does not.
      for (const category of categories) {
        if (!(category.key in this.collapsedCategories)) {
          this.collapsedCategories[category.key] = category.key !== 'Ship'
        }
        for (const group of category.groups) {
          const key = `${category.key}/${group.name}`
          if (!(key in this.collapsedGroups)) this.collapsedGroups[key] = true
        }
      }
    },

    async loadTree() {
      if (this.treeLoaded) return
      await this.reloadTree()
      this.treeLoaded = true
    },

    /** Read the tree again. Each ship's fit count is part of it, so fits changing means the tree changed. */
    async reloadTree() {
      const { categories } = await api.shipTree()
      this.applyTree(categories)
    },

    toggleCategory(key: string) {
      this.collapsedCategories[key] = !this.collapsedCategories[key]
    },

    toggleGroup(category: string, group: string) {
      const key = `${category}/${group}`
      this.collapsedGroups[key] = !this.collapsedGroups[key]
    },

    /** Show or hide one ship's fits under its row in the tree. */
    async toggleShipFits(shipId: number) {
      this.expandedShips[shipId] = !this.expandedShips[shipId]
      if (this.expandedShips[shipId] && !this.shipFitsById[shipId]) {
        await this.loadShipFits(shipId)
      }
    },

    async selectShip(shipId: number) {
      this.shipId = shipId
      this.shipLoading = true
      try {
        const detail = await api.ship(shipId)
        this.ship = { id: detail.ship.id, name: detail.ship.name, iconId: detail.ship.iconId, graphicId: detail.ship.graphicId, image: detail.ship.image }
        this.shipSlots = detail.slots
        this.shipFitsById[shipId] = detail.fits
      } finally {
        this.shipLoading = false
      }
    },

    /** Re-read one ship's fits; the tree row and the detail panel share the one list. */
    async loadShipFits(shipId: number) {
      this.loadingFits[shipId] = true
      try {
        const { fits } = await api.fits(shipId)
        this.shipFitsById[shipId] = fits
      } catch (error) {
        this.setError(error)
      } finally {
        this.loadingFits[shipId] = false
      }
    },

    /** Re-read the selected ship's fits; its tree row and the detail panel share one list. */
    async refreshShipFits() {
      if (this.shipId === null) return
      await this.loadShipFits(this.shipId)
    },

    /** A fit this browser just added: that ship's badge goes up by one. */
    noteFitAdded(shipId: number) {
      const ship = findShip(this.categories, shipId)
      if (ship) ship.fitCount = (ship.fitCount ?? 0) + 1
      if (shipId === this.shipId || this.expandedShips[shipId]) void this.loadShipFits(shipId)
      else delete this.shipFitsById[shipId]
    },

    /** A fit was renamed or deleted elsewhere: re-read whichever list was showing it. */
    invalidateFit(fitId: number) {
      for (const key of Object.keys(this.shipFitsById)) {
        const shipId = Number(key)
        if (!this.shipFitsById[shipId]?.some((fit) => fit.id === fitId)) continue
        if (this.shipId === shipId || this.expandedShips[shipId]) void this.loadShipFits(shipId)
        else delete this.shipFitsById[shipId]
      }
    },

    /**
     * The set of fits changed on the server: read the tree (its counts changed) and the
     * fit lists that are on screen -- the selected ship's and every expanded ship's.
     */
    async refreshFits() {
      this.shipFitsById = {}
      await this.reloadTree()
      const onScreen = new Set<number>(
        Object.keys(this.expandedShips)
          .map(Number)
          .filter((shipId) => this.expandedShips[shipId]),
      )
      if (this.shipId !== null) onScreen.add(this.shipId)
      for (const shipId of onScreen) await this.loadShipFits(shipId)
    },

    /**
     * Fetch the fittings the logged-in pilot has saved in game and import them under
     * their ships. Nothing is written back to EVE, and fittings pyfa already has are
     * left alone (see `web/services/esiFittings.py`).
     */
    async importFromEsi() {
      this.importing = true
      this.error = ''
      try {
        const result = await api.importEsiFittings()
        // Our own `fits.imported` event is already on its way; this refresh is the
        // reliable one, and `quietUntil` keeps the handler in @/stores/fitting from
        // running the same queries again.
        this.quietUntil = Date.now() + 5000
        this.showNotice(importNotice(result))
        await this.refreshFits()
      } catch (error) {
        this.setError(error)
      } finally {
        this.importing = false
      }
    },

    setError(error: unknown) {
      this.error = errorText(error)
      window.setTimeout(() => {
        if (this.error) this.error = ''
      }, 8000)
    },

    showNotice(text: string, timeout = 8000) {
      this.notice = text
      window.setTimeout(() => {
        if (this.notice === text) this.notice = ''
      }, timeout)
    },

    async searchShips(query: string) {
      this.shipFilter = query
      if (!query.trim()) {
        this.shipSearchResults = null
        return
      }
      const { results } = await api.searchShips(query.trim())
      this.shipSearchResults = results
    },

    async searchItems(query: string, scope?: 'market' | 'everything' | 'implants') {
      this.itemQuery = query
      if (scope) this.itemScope = scope
      if (!query.trim()) {
        this.itemResults = []
        return
      }
      this.itemSearching = true
      this.itemSearchError = ''
      try {
        const { results } = await api.searchItems(query.trim(), this.itemScope)
        this.itemResults = results
      } catch (error) {
        this.itemResults = []
        this.itemSearchError = error instanceof Error ? error.message : String(error)
      } finally {
        this.itemSearching = false
      }
    },

    /**
     * Load everything the details pane shows for one item.
     *
     * `fit` says what the click was on (see `FittedKind`). Passing it makes the attribute
     * list the values the fit gives that item instead of the type's own, which is the
     * point of the pane once a fit is open. Only a module in a rack can be the target of
     * a charge, so the charge list asks about the fit only when that is what was clicked.
     */
    async selectItem(item: Item, fit?: { id: number; position?: number | null; kind?: FittedKind }) {
      const fitted = fit && fit.position != null ? fit : null
      const moduleRow = fitted && (fitted.kind === undefined || fitted.kind === 'module') ? fitted : null
      this.selectedItem = item
      this.detailLoading = true
      this.selectedAttributes = []
      this.selectedCharges = []
      this.selectedVariations = []
      this.selectedRequirements = []
      try {
        const [attributes, charges, variations, requirements] = await Promise.all([
          api.attributes(item.id, fitted?.id, fitted?.position ?? undefined, fitted?.kind),
          api.charges(item.id, moduleRow?.id, moduleRow?.position ?? undefined),
          api.variations(item.id),
          api.requirements(item.id),
        ])
        this.selectedAttributes = attributes.rows
        this.selectedAttributesModified = attributes.modified
        this.selectedCharges = charges.charges.map((entry) => entry.item)
        this.selectedVariations = variations.variations
        this.selectedRequirements = requirements.skills
      } catch {
        // an item without attributes (rare) is not worth surfacing as an error
      } finally {
        this.detailLoading = false
      }
    },

    clearItem() {
      this.selectedItem = null
      this.selectedAttributes = []
      this.selectedCharges = []
      this.selectedVariations = []
      this.selectedRequirements = []
    },
  },
})
