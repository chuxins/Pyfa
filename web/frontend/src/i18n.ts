/**
 * UI chrome translations.
 *
 * Keys are the English source strings, which is the same convention pyfa's own
 * gettext catalogue uses (`locale/lang.pot`, read with `wx.GetTranslation`). That
 * keeps the two in step: a term the desktop already translates is written here the
 * way `locale/zh_CN/LC_MESSAGES/lang.po` writes it, so the web UI and the desktop
 * application say the same thing in Chinese.
 *
 * Only the *chrome* lives here. Item names, attribute names, market groups and the
 * like come from the server's game data. A refused edit comes from the server too, but
 * as an English sentence plus a code and its values, which `@/errors` renders through
 * this same catalogue; see `web/docs/web.md`, "Interface language".
 */

import { ref } from 'vue'

export type LocaleCode = 'en_US' | 'zh_CN'

export const LOCALES: { code: LocaleCode; label: string }[] = [
  { code: 'zh_CN', label: '中文（简体）' },
  { code: 'en_US', label: 'English' },
]

/** Set when the user picks a language, so the choice survives a reload. */
const STORAGE_KEY = 'pyfa.locale'

const ZH_CN: Record<string, string> = {
  // -- top bar and placeholders (App.vue) ----------------------------------------------
  Undo: '撤销',
  Redo: '恢复',
  'Clear fit': '清空装配',
  'working…': '处理中…',
  'Hide item browser': '隐藏物品浏览器',
  'Show item browser': '显示物品浏览器',
  'Sign out': '退出登录',
  'Sign in with EVE': '使用 EVE 登录',
  'Sign in to build fits': '登录后即可配置装配',
  'EVE SSO is how pyfa web knows whose fits to load.': 'pyfa web 通过 EVE SSO 判断该加载谁的装配。',
  'EVE SSO is not configured on this server.': '此服务器未配置 EVE SSO。',
  'Set PYFA_WEB_SSO_CLIENT_ID, or run the server with --dev-login for development.':
    '请设置 PYFA_WEB_SSO_CLIENT_ID，或在开发时用 --dev-login 启动服务器。',
  'the sign-in took too long or was already used; start again': '本次登录已超时或已被使用，请重新登录。',
  'the sign-in was cancelled at EVE': '已在 EVE 取消登录。',
  "EVE's login service could not be reached; try again in a moment": '无法连接 EVE 登录服务，请稍后再试。',
  'EVE did not accept the sign-in; the server log has the reason': 'EVE 未接受本次登录，原因见服务器日志。',
  'the sign-in did not complete': '登录未完成。',
  'No fit open': '未打开装配',
  'Pick a ship on the left, then open one of its fits or create a new one.':
    '在左侧选择舰船，然后打开已有装配或新建一个。',
  'gamedata build {build}': '游戏数据版本 {build}',
  'Interface language': '界面语言',

  // -- ship browser ---------------------------------------------------------------------
  'Search ships…': '搜索舰船…',
  'Results ({count})': '搜索结果（{count}）',
  'New fit': '新建装配',
  'No saved fits yet': '暂无保存的装配',
  'Import my EVE fits': '导入我的 EVE 装配',
  'importing…': '导入中…',
  'reading fits…': '正在读取装配…',
  'Show the fits saved for this ship': '显示该舰船保存的装配',
  'Imported {count} fits from {name}': '已从 {name} 导入 {count} 个装配',
  'EVE has no fitting saved for {name}': '{name} 在 EVE 中没有保存的装配',
  '{count} were already in pyfa': '其中 {count} 个 pyfa 中已有',
  '{count} are for ships this game data does not know': '其中 {count} 个属于本地游戏数据中没有的舰船',
  '{count} could not be read': '其中 {count} 个无法读取',
  booster: '增效剂',
  hi: '高',
  med: '中',
  low: '低',
  rig: '改装',
  sub: '子系统',

  // -- item browser ---------------------------------------------------------------------
  'Search items (prefix re: for regex)…': '搜索物品（前缀 re: 使用正则）…',
  Market: '市场',
  Everything: '全部',
  Implants: '植入体',
  'searching…': '搜索中…',
  '{count} results': '{count} 个结果',
  add: '添加',
  'Search for a module, charge, drone, implant or booster.': '可搜索装备、弹药、无人机、植入体或增效剂。',
  'click to fit into a free slot': '点击装入空闲槽位',
  'click to load into the selected module': '点击装填到选中装备',
  'click to add a stack of 5': '点击添加一组（5 个）',
  'click to add a squadron': '点击添加一个中队',
  'click to add to implants': '点击添加到植入体',
  'click to add to boosters': '点击添加到增效剂',
  'click to put in the cargo hold': '点击放入货舱',
  'ships cannot be fitted to a fit': '舰船不能装配到装配中',

  // -- item details ---------------------------------------------------------------------
  'Add to fit': '添加到装配',
  Attributes: '属性',
  'Charges ({count})': '弹药（{count}）',
  'Variants ({count})': '变种（{count}）',
  'Skills ({count})': '技能（{count}）',
  'only attributes changed by the fit': '仅显示被装配改变的属性',
  'No published attributes.': '无公开属性。',
  load: '装填',
  'This item takes no charges.': '该物品不需要弹药。',
  'No variants.': '无变种。',
  'No skill requirements.': '无技能需求。',
  'level {level}': '等级 {level}',
  '(base {value})': '（基础 {value}）',

  // -- fitting view ---------------------------------------------------------------------
  'High power': '高槽',
  'Medium power': '中槽',
  'Low power': '低槽',
  'Rig slot': '改装件',
  Subsystem: '子系统',
  Service: '服务',
  Mode: '模式',
  System: '系统',
  offline: '离线',
  online: '在线',
  active: '激活',
  overheated: '超载',
  '{state} — click to cycle, ctrl-click to offline, right-click to overheat':
    '{state} — 单击切换，Ctrl+单击离线，右键超载',
  // -- the high rack's weapon grouping --------------------------------------------------
  'group weapons': '武器编组',
  'ungroup weapons': '取消编组',
  'Group the same weapons in this rack so one click or charge reaches them all':
    '把本槽位中同型的武器编为一组：一次点击或一次装填即可作用于整组',
  'Ungroup: every weapon goes back to being on its own': '取消编组：恢复每个武器单独操作',
  'grouped ×{count}': '编组 ×{count}',
  '{count} of the same weapon act together: a state click or a charge reaches them all':
    '{count} 件同型武器联动：切换状态或装填弹药会同时作用于整组',
  ' · the whole weapon group moves together': ' · 整组一起切换',
  mutated: '已变异',
  'load…': '装填…',
  'click to inspect the loaded charge as fitted': '点击查看所装弹药在装配后的实际属性',
  Remove: '移除',
  Drones: '无人机',
  '{active} / {max} active': '已激活 {active} / {max}',
  'active {count}': '激活 {count}',
  idle: '闲置',
  Fighters: '铁骑舰载机',
  launched: '已出击',
  'in bay': '在库',
  'from character': '来自角色',
  'from fit': '来自装配',
  switch: '切换',
  Boosters: '增效剂',
  inactive: '未激活',
  Cargo: '货舱',
  'Click an item in the browser below to fit it. Charges go into the selected module. Click a row of the fit to inspect it as fitted.':
    '在下方浏览器中点击物品即可装配，弹药会装填到选中的装备；点击装配中的任意一行可查看装配后的实际属性。',

  // -- stats pane -----------------------------------------------------------------------
  Firepower: '火力',
  'vs target profile': '对目标属性',
  'Weapon DPS': '武器秒伤',
  'Weapon spool': '武器预热',
  'Drone DPS': '无人机秒伤',
  'Total DPS': '总秒伤',
  'Total spool': '总预热',
  'Total volley': '总齐射伤害',
  Capacitor: '电容',
  Capacity: '容量',
  'Recharge / usage': '回充 / 消耗',
  Stable: '稳定',
  Lasts: '可维持',
  yes: '是',
  Delta: '变化量',
  'Neut resistance': '电容中和抗性',
  Tank: '恢复',
  'hp/s': '生命/秒',
  raw: '原始',
  effective: '等效',
  'Passive shield': '被动护盾回充',
  'Shield repair': '护盾维修',
  'Armor repair': '装甲维修',
  'Hull repair': '结构维修',
  Defence: '防御',
  EM: '电磁',
  TH: '热能',
  KIN: '动能',
  EXP: '爆炸',
  Shield: '护盾',
  Armor: '装甲',
  Hull: '结构',
  'Hit points': '生命值',
  total: '合计',
  'Effective HP': '有效 HP',
  'Incoming damage': '承受伤害',
  Resources: '装配资源',
  CPU: 'CPU',
  Powergrid: '能量栅格',
  Calibration: '校准',
  Turrets: '炮台',
  Launchers: '发射器',
  'Drone bay': '无人机仓库',
  Bandwidth: '无人机带宽',
  'Fighter tubes': '铁骑舰载机发射管',
  'Targeting & misc': '锁定与其它',
  Targets: '最大锁定数',
  Range: '锁定范围',
  'Scan resolution': '扫描分辨率',
  'Sensor strength': '传感器强度',
  'Jam chance': '被干扰概率',
  Speed: '速度',
  'Align time': '起跳时间',
  Signature: '信号半径',
  'Warp speed': '曲速航速',
  'Probe size': '探针信号半径',
  'Warp core strength': '跃迁核心强度',
  Mass: '质量',
  'Remote reps': '遥修',
  shield: '护盾',
  armor: '装甲',
  hull: '结构',
  'hull / cap': '结构 / 电容',
  Mining: '采矿',
  'Total yield': '总产出',
  'Miner / drone': '采矿器 / 无人机',
  'Not computed': '未计算',

  // -- server-provided enumerations -----------------------------------------------------
  // The engine sends these as plain strings; naming them here means the pane reads
  // Chinese without the server having to know about the UI language.
  Radar: '雷达',
  Ladar: '光雷达',
  Magnetometric: '磁力计',
  Gravimetric: '引力',
  Uniform: '均匀',

  // -- messages the front end writes itself ---------------------------------------------
  'No fitted module can load this charge': '没有已装配的装备能装填该弹药',
  'Loaded into {count} modules': '已装填到 {count} 个装备',
  'This fit was deleted': '该装配已被删除',

  // -- refusals from the server ----------------------------------------------------------
  // The templates are the sentences `web/services/commands.py` writes, keyed by code in
  // `@/errors`; the words they interpolate are named the way the desktop names them, so
  // most of them are `locale/lang.po` entries ("High" -> 高, "Turrets" -> 炮台).
  High: '高',
  Med: '中',
  Low: '低',
  Rig: '改装',
  turret: '炮台',
  launcher: '发射器',
  "the engine refused to run '{command}'; the item may not fit, or the target is invalid":
    '装配引擎拒绝了「{command}」：该物品可能装不下，或目标无效。',
  'there is no item with id {itemId} in the game data': '游戏数据中没有 id 为 {itemId} 的物品。',
  "'{name}' is ammunition ({group}), not a module: load it into a fitted module instead":
    '「{name}」属于{group}，是弹药而不是装备：请把它装填到已装配的装备里。',
  "'{name}' is a {group}, not a module, so it cannot go into a slot":
    '「{name}」属于{group}，不是装备，无法装入槽位。',
  "'{name}' has no slot to fit into": '「{name}」没有可以装入的槽位。',
  "the fit has no free {rack} slot for '{name}'": '没有空闲的{rack}槽位可供「{name}」使用。',
  "'{name}' is restricted to certain hulls and cannot be fitted to a {ship}":
    '「{name}」只能装配在特定船体上，{ship} 不行。',
  "'{name}' is a capital-size module and is too big for a {ship}": '「{name}」是旗舰级装备，{ship} 装不下。',
  "'{name}' is the wrong size for the rig slots of a {ship}":
    '「{name}」的尺寸与 {ship} 的改装件槽位不符。',
  "the fit has no free {hardpoint} hardpoint for '{name}'":
    '没有空闲的{hardpoint}挂点可供「{name}」使用。',
  "'{name}' does not fit this fit": '「{name}」装不进这个装配。',
  "'{name}' is already {state}": '「{name}」已处于{state}状态。',
  'undo failed; the fit may have changed underneath': '撤销失败：装配可能在后台发生了变化。',
  'redo failed; the fit may have changed underneath': '恢复失败：装配可能在后台发生了变化。',
  // -- a failed ESI import (see @/errors, web/services/esiFittings.py) ------------------
  'this account has no {server} EVE login stored on the server; sign in with EVE again':
    '此账号在服务器上没有保存 {server} 的 EVE 登录信息，请重新使用 EVE 登录。',
  'EVE no longer accepts the stored login; sign in with EVE again': 'EVE 不再接受已保存的登录信息，请重新使用 EVE 登录。',
  "EVE's ESI could not be reached; try again in a moment": '无法连接 EVE 的 ESI，请稍后再试。',
  'EVE refused to hand over the fittings ({reason})': 'EVE 拒绝提供装配方案（{reason}）。',
  'EVE did not answer with a list of fittings, so none were imported':
    'EVE 没有返回装配方案列表，因此没有导入任何内容。',
  'the fittings could not be imported; the server log has the reason': '无法导入装配方案，原因见服务器日志。',
}

/** The English catalogue is the identity: `t()` falls back to the key itself. */
const CATALOGUES: Partial<Record<LocaleCode, Record<string, string>>> = {
  zh_CN: ZH_CN,
}

export const locale = ref<LocaleCode>('en_US')

function isSupported(code: string | null | undefined): code is LocaleCode {
  return code === 'en_US' || code === 'zh_CN'
}

function readStored(): LocaleCode | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return isSupported(value) ? value : null
  } catch {
    // Private mode or a locked-down browser: fall back to detection
    return null
  }
}

/** Switch the chrome language; ``persist`` records it as an explicit choice. */
export function setLocale(code: LocaleCode, persist = true) {
  locale.value = code
  if (typeof document !== 'undefined') {
    document.documentElement.lang = code === 'zh_CN' ? 'zh-CN' : 'en'
  }
  if (!persist) return
  try {
    window.localStorage.setItem(STORAGE_KEY, code)
  } catch {
    // Nothing to do; the choice only lives for this page
  }
}

/**
 * Decide the initial chrome language.
 *
 * An explicit choice wins, then the server's language (`/api/meta`), then the
 * browser's, then English. Starting from the server's language matters because it is
 * also the language of the game data the pane is showing: ``python -m web
 * --language zh_CN`` gives every browser a Chinese UI without anyone having to
 * pick one.
 */
export function initLocale(serverLanguage?: string | null) {
  const stored = readStored()
  if (stored) {
    setLocale(stored, false)
    return
  }
  if (isSupported(serverLanguage)) {
    setLocale(serverLanguage, false)
    return
  }
  const browser = typeof navigator === 'undefined' ? '' : navigator.language
  setLocale(browser.toLowerCase().startsWith('zh') ? 'zh_CN' : 'en_US', false)
}

/**
 * Translate one chrome string.
 *
 * Missing keys fall through to the source string, so a partially translated
 * catalogue degrades to English rather than to blank labels. Reads ``locale`` while
 * it runs, which is what makes ``t()`` reactive inside a template.
 */
export function t(source: string, params?: Record<string, string | number>): string {
  const catalogue = CATALOGUES[locale.value]
  let text = catalogue?.[source] ?? source
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value))
    }
  }
  return text
}