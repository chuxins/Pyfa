/**
 * Typed client for the pyfa web API.
 */
export interface ItemImage {
  kind: 'icons' | 'renders'
  id: number
}

export interface Item {
  id: number
  name: string
  iconId: number | null
  graphicId: number | null
  image: ItemImage | null
  group: string | null
  category: string | null
  itemKind: 'module' | 'charge' | 'drone' | 'fighter' | 'implant' | 'booster' | 'ship' | 'cargo'
  metaGroup?: string | null
  metaLevel?: number
  description?: string | null
}

/**
 * A row of a fit, as the details pane asks about it: what the click was on.
 *
 * `module` is a rack slot; `drone`, `fighter`, `cargo`, `implant` and `booster` name a
 * row of that list; `moduleCharge` is the charge loaded in a module, which is reached
 * through the module it sits in (`position`). The server checks that the item the browser
 * had in mind is the one actually there, so a row is never answered with another row's
 * numbers (see `web/api/items.py`).
 */
export type FittedKind = 'module' | 'drone' | 'fighter' | 'cargo' | 'implant' | 'booster' | 'moduleCharge'

export interface ShipSummary {
  id: number
  name: string
  iconId: number | null
  graphicId: number | null
  image: ItemImage | null
  /** How many of this user's fits use the ship; only the tree counts them */
  fitCount?: number
}

export interface ShipGroup {
  id: number
  name: string
  ships: ShipSummary[]
}

export interface ShipCategory {
  /** English category name, stable across languages -- `name` is translated */
  key: string
  name: string
  groups: ShipGroup[]
}

export interface FitSummary {
  id: number
  name: string
  booster: boolean
  shipId: number
  shipName: string | null
  shipImage?: ItemImage | null
  modified: string | null
  notes: string | null
}

/** Why one of the pilot's in-game fittings did not arrive (see `web/services/esiFittings.py`) */
export type EsiImportSkipReason = 'alreadyImported' | 'unknownShip' | 'unreadable'

export interface EsiImportSkipped {
  name: string
  shipId: number
  reason: EsiImportSkipReason
}

export interface EsiImportResult {
  character: { id: number; name: string; server: string }
  /** How many fittings EVE has for this pilot, imported or not */
  total: number
  imported: (FitSummary & { esiFittingId: number | null })[]
  skipped: EsiImportSkipped[]
}

export interface Module {
  position: number
  slot: string
  isEmpty: boolean
  itemId: number | null
  item: Item | null
  state: 'offline' | 'online' | 'active' | 'overheated'
  amount: number
  charge?: { item: Item; amount: number } | null
  /** "turret", "launcher" or null: what the high rack can group as weapons */
  hardpoint?: 'turret' | 'launcher' | null
  isMutated?: boolean
  mutations?: Record<string, number>
  spool?: { type: number; amount: number }
  isValidState?: boolean
  maxRange?: number | null
}

export interface Drone {
  itemId: number
  item: Item
  amount: number
  amountActive: number
}

export interface CargoItem {
  itemId: number
  item: Item
  amount: number
}

export interface Implant {
  itemId: number
  item: Item
  active: boolean
}

export interface Fighter {
  itemId: number
  item: Item
  amount: number
  active: boolean
  abilities: { effectId: number; name: string | null; active: boolean }[]
}

export interface DamageTypes {
  em: number
  thermal: number
  kinetic: number
  explosive: number
  pure: number
  total: number
}

export interface Stats {
  resources: {
    hardpoints: { turret: { used: number; total: number }; launcher: { used: number; total: number } }
    calibration: { used: number; total: number }
    cpu: { used: number; total: number }
    powergrid: { used: number; total: number }
    drones: {
      active: number
      maxActive: number
      bayUsed: number
      bayTotal: number
      bandwidthUsed: number
      bandwidthTotal: number
    }
    fighters: { tubesUsed: number; tubesTotal: number; bayUsed: number; bayTotal: number }
    cargo: { used: number; total: number }
    droneControlRange: number
  }
  firepower: {
    weapon: SpooledDamage
    drone: SpooledDamage
    volley: SpooledDamage
    dps: SpooledDamage
    defaultSpoolValue: number
    hasTargetProfile: boolean
  }
  mining: {
    miner: { yield: number; drain: number }
    drone: { yield: number; drain: number }
    total: { yield: number; drain: number }
  }
  capacitor: {
    capacity: number
    delta: number
    recharge: number
    used: number
    stable: boolean
    state: number
    resistance: number
    effectiveCapacity: number
  }
  tank: {
    normal: TankRow
    effective: TankRow
    sustained: TankRow
    effectiveSustained: TankRow
  }
  resistances: {
    hp: { shield: number; armor: number; hull: number; total: number }
    ehp: { shield: number; armor: number; hull: number; total: number }
    resistances: Record<'shield' | 'armor' | 'hull', Record<'em' | 'thermal' | 'kinetic' | 'explosive', number>>
    damagePattern: { em: number; thermal: number; kinetic: number; explosive: number } | null
    damagePatternName: string | null
    targetProfileName: string | null
  }
  targeting: {
    targets: number
    maxTargetRange: number
    scanResolution: number
    sensorStrength: number
    scanType: string
    jamChance: number
    droneControlRange: number
    speed: number
    alignTime: number
    signatureRadius: number
    warpSpeed: number
    maxWarpDistance: number
    mass: number
    agility: number
    probeSize: number | null
    warpCoreStrength: number
    holds: { attr: string; label: string; capacity: number }[]
    lockTimes: { name: string; radius: number; time: number }[]
  }
  remoteReps: {
    value: { shield: number; armor: number; hull: number; capacitor: number }
    preSpool: { shield: number; armor: number; hull: number; capacitor: number }
    fullSpool: { shield: number; armor: number; hull: number; capacitor: number }
  }
  errors: Record<string, string>
}

export interface SpooledDamage {
  value: DamageTypes
  preSpool: DamageTypes
  fullSpool: DamageTypes
}

export interface TankRow {
  passiveShield: number
  shieldRepair: number
  armorRepair: number
  hullRepair: number
  armorRepairPreSpool: number
  armorRepairFullSpool: number
}

export interface History {
  canUndo: boolean
  canRedo: boolean
  depth: number
  undoName: string | null
  redoName: string | null
}

export interface Fit {
  id: number
  name: string
  notes: string | null
  booster: boolean
  created: string | null
  modified: string | null
  factorReload: boolean
  ignoreRestrictions: boolean
  implantLocation: number
  isStructure: boolean
  ship: { id: number; item: Item; slots: Record<string, number> }
  character: { id: number; name: string } | null
  damagePattern: { id: number; name: string; em: number; thermal: number; kinetic: number; explosive: number } | null
  targetProfile: unknown
  racks: Record<string, Module[]>
  drones: Drone[]
  fighters: Fighter[]
  cargo: CargoItem[]
  implants: Implant[]
  appliedImplants: Implant[]
  boosters: { itemId: number; item: Item; active: boolean; sideEffects: unknown[] }[]
  projected: {
    modules: Module[]
    drones: Drone[]
    fighters: Fighter[]
    fits: unknown[]
    commandFits: unknown[]
  }
  stats?: Stats
  history?: History
}

/**
 * A refusal the server explained: the English message, a code naming the reason, and
 * the values that belong in the sentence. See `@/errors` and `web/services/commands.py`.
 */
export interface ApiErrorDetail {
  message: string
  code: string
  params: Record<string, string | number>
}

export class ApiError extends Error {
  status: number
  /** Set when the server sent a code with the failure, null when it only sent text. */
  detail: ApiErrorDetail | null
  constructor(status: number, message: string, detail: ApiErrorDetail | null = null) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })
  if (response.status === 204) return undefined as T
  const text = await response.text()
  let body: any = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }
  if (!response.ok) {
    const detail = body && typeof body === 'object' ? body.detail : body
    if (typeof detail === 'string') throw new ApiError(response.status, detail)
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
      throw new ApiError(response.status, detail.message, {
        message: detail.message,
        code: typeof detail.code === 'string' ? detail.code : 'engineRefused',
        params: detail.params ?? {},
      })
    }
    throw new ApiError(response.status, response.statusText)
  }
  return body as T
}

/**
 * The query that reads a row of a fit, or nothing at all when there is no fit.
 *
 * Both `attributes` and `charges` take the same three answers -- which fit, which row,
 * and what kind of row -- and each endpoint has its own default for the kind.
 */
function fitQuery(fitId?: number, position?: number, kind?: FittedKind): string {
  if (fitId === undefined || position === undefined) return ''
  const query = new URLSearchParams({ fitId: String(fitId), position: String(position) })
  if (kind !== undefined) query.set('kind', kind)
  return `?${query}`
}

export const api = {
  meta: () =>
    request<{
      pyfaVersion: string
      webVersion: string
      language: string
      gamedata: { build: string; date: string }
      sso: { server: string; configured: boolean; devBypass: boolean }
      user: { id: number; characterId: number; characterName: string } | null
    }>('/api/meta'),

  me: () => request<{ authenticated: boolean; user?: any }>('/api/auth/me'),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),

  shipTree: () => request<{ categories: ShipCategory[] }>('/api/ships/tree'),
  searchShips: (q: string) => request<{ results: ShipSummary[] }>(`/api/ships/search?q=${encodeURIComponent(q)}`),
  ship: (shipId: number) =>
    request<{ ship: Item; slots: Record<string, number>; fits: FitSummary[] }>(`/api/ships/${shipId}`),

  fits: (shipId?: number) =>
    request<{ fits: FitSummary[] }>(`/api/fits${shipId === undefined ? '' : `?shipId=${shipId}`}`),
  searchFits: (q: string) => request<{ fits: FitSummary[] }>(`/api/fits?q=${encodeURIComponent(q)}`),
  fit: (fitId: number, stats = true) => request<Fit>(`/api/fits/${fitId}?stats=${stats}`),
  stats: (fitId: number) => request<{ id: number; stats: Stats }>(`/api/fits/${fitId}/stats`),
  createFit: (shipId: number, name?: string) =>
    request<Fit>('/api/fits', { method: 'POST', body: JSON.stringify({ shipId, name }) }),
  updateFit: (fitId: number, patch: Partial<{ name: string; notes: string; factorReload: boolean }>) =>
    request<Fit>(`/api/fits/${fitId}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  deleteFit: (fitId: number) => request<void>(`/api/fits/${fitId}`, { method: 'DELETE' }),
  duplicateFit: (fitId: number) => request<FitSummary>(`/api/fits/${fitId}/duplicate`, { method: 'POST' }),

  /** Fetch the fittings the pilot saved in game and import them under their ships */
  importEsiFittings: () => request<EsiImportResult>('/api/esi/fittings/import', { method: 'POST' }),

  commands: () => request<{ commands: { name: string; summary: string; requires: string[]; args: Record<string, string> }[] }>('/api/commands'),
  runCommand: (fitId: number, command: string, args: Record<string, unknown>) =>
    request<Fit>(`/api/fits/${fitId}/commands`, { method: 'POST', body: JSON.stringify({ command, args }) }),
  undo: (fitId: number) => request<Fit>(`/api/fits/${fitId}/undo`, { method: 'POST' }),
  redo: (fitId: number) => request<Fit>(`/api/fits/${fitId}/redo`, { method: 'POST' }),
  resetFit: (fitId: number) => request<void>(`/api/fits/${fitId}/reset`, { method: 'POST' }),
  history: (fitId: number) => request<History>(`/api/fits/${fitId}/history`),
  chargeTargets: (fitId: number, chargeItemId: number) =>
    request<{ targets: { position: number; itemId: number; name: string | null }[] }>(
      `/api/fits/${fitId}/charge-targets?chargeItemId=${chargeItemId}`,
    ),

  searchItems: (q: string, scope = 'market') =>
    request<{ results: Item[] }>(`/api/items/search?q=${encodeURIComponent(q)}&scope=${scope}&limit=60`),
  item: (itemId: number) => request<Item>(`/api/items/${itemId}`),
  attributes: (itemId: number, fitId?: number, position?: number, kind?: FittedKind) =>
    request<{ itemId: number; modified: boolean; rows: AttributeRow[] }>(
      `/api/items/${itemId}/attributes${fitQuery(fitId, position, kind)}`,
    ),
  charges: (itemId: number, fitId?: number, position?: number) =>
    request<{ charges: { item: Item }[] }>(
      `/api/items/${itemId}/charges${fitQuery(fitId, position)}`,
    ),
  variations: (itemId: number) => request<{ variations: Item[] }>(`/api/items/${itemId}/variations`),
  requirements: (itemId: number) => request<{ skills: { skillId: number; name: string; level: number }[] }>(`/api/items/${itemId}/requirements`),
}

export interface AttributeRow {
  id: number | null
  name: string
  displayName: string
  value: number
  baseValue?: number | null
  unit: string | null
  highIsGood: boolean
  description?: string | null
}

export function imageUrl(image: ItemImage | null | undefined, size = 1): string | null {
  if (!image) return null
  return `/img/${image.kind}/${image.id}${size === 2 ? '@2x' : '@1x'}`
}
