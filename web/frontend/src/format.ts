/**
 * Number formatting, ported from the desktop application.
 *
 * `gui/utils/numberFormatter.formatAmount` is what turns 1234567 into "1.23M" in
 * the fitting window. The server sends raw numbers plus the rounding hints, so
 * this has to match the Python version exactly or the browser would show
 * different figures than the desktop for the same fit. Kept in sync with
 * `gui/utils/numberFormatter.py` and `eos/utils/round.py`.
 */

const POS_ORDERS = [9, 6, 3]
const NEG_ORDERS = [-6, -3]

function posSuffix(key: number, currency: boolean): string {
  if (key === 3) return 'k'
  if (key === 6) return 'M'
  if (key === 9) return currency ? 'B' : 'G'
  return ''
}

function negSuffix(key: number): string {
  if (key === -6) return '\u03bc'
  if (key === -3) return 'm'
  return ''
}

export function roundToPrec(value: number, prec: number, nsValue?: number): number {
  if (Math.trunc(value) === value) return Math.trunc(value)
  const basis = nsValue === undefined ? Math.abs(value) : Math.abs(nsValue)
  let roundFactor = Math.trunc(prec - Math.floor(Math.log10(basis)) - 1)
  if (roundFactor < 0) roundFactor = 0
  const rounded = Number(value.toFixed(Math.min(roundFactor, 100)))
  return Math.trunc(rounded) === rounded ? Math.trunc(rounded) : rounded
}

export interface AmountOptions {
  prec?: number
  lowest?: number
  highest?: number
  currency?: boolean
  forceSign?: boolean
  unitName?: string | null
}

export function formatAmount(value: number | null | undefined, options: AmountOptions = {}): string {
  const { prec = 3, lowest = 0, highest = 0, currency = false, forceSign = false, unitName = null } = options

  if (value === null || value === undefined) return ''
  if (value === Number.POSITIVE_INFINITY) return unitName === null ? '\u221e' : `\u221e ${unitName}`

  const posLowest = Math.min(...POS_ORDERS)
  const negHighest = Math.max(...NEG_ORDERS)

  let mantissa = value
  let suffix = ''

  if (Math.abs(value) > 1 && highest >= posLowest) {
    for (const key of POS_ORDERS) {
      if (Math.abs(value) >= 10 ** key && key <= highest) {
        mantissa = value / 10 ** key
        suffix = posSuffix(key, currency)
        const index = POS_ORDERS.indexOf(key)
        if (index === 0) break
        const prevKey = POS_ORDERS[index - 1]
        if (prevKey > highest) break
        const orderDiff = 10 ** (prevKey - key)
        if (roundToPrec(mantissa, prec) >= orderDiff) {
          mantissa = mantissa / orderDiff
          suffix = posSuffix(prevKey, currency)
        }
        break
      }
    }
  } else if (Math.abs(value) < 1 && value !== 0 && lowest <= negHighest) {
    for (const key of NEG_ORDERS) {
      const idx = NEG_ORDERS.indexOf(key)
      const nextKey = idx + 1 < NEG_ORDERS.length ? NEG_ORDERS[idx + 1] : 0
      if (Math.abs(value) < 10 ** nextKey && key >= lowest) {
        mantissa = value / 10 ** key
        suffix = negSuffix(key)
        if (nextKey > highest) break
        const orderDiff = 10 ** (nextKey - key)
        if (roundToPrec(mantissa, prec) >= orderDiff) {
          mantissa = mantissa / orderDiff
          suffix = nextKey !== 0 ? posSuffix(nextKey, currency) : ''
        }
        break
      }
    }
  }

  mantissa = roundToPrec(mantissa, prec)
  const sign = forceSign === true && mantissa > 0 ? '+' : ''
  if (unitName === null) return `${sign}${mantissa}${suffix}`
  return `${sign}${mantissa} ${suffix}${unitName}`
}

/** "12.3 km" style helper for stat rows that carry a unit. */
export function formatValue(
  value: number | null | undefined,
  unit?: string | null,
  options: AmountOptions = {},
): string {
  if (value === null || value === undefined) return '\u2013'
  const text = formatAmount(value, options)
  return unit ? `${text}${unit.startsWith('%') ? '' : ' '}${unit}` : text
}

export function formatIsk(value: number | null | undefined): string {
  if (value === null || value === undefined) return '\u2013'
  return `${formatAmount(value, { prec: 3, lowest: 3, highest: 9, currency: true })} ISK`
}

/** Damage profile as a compact "EM + TH + KIN + EXP" string. */
export function formatDamageTypes(
  damage: { em: number; thermal: number; kinetic: number; explosive: number; pure?: number } | null | undefined,
): string {
  if (!damage) return '\u2013'
  const parts = [damage.em, damage.thermal, damage.kinetic, damage.explosive]
  if (damage.pure) parts.push(damage.pure)
  return parts.map((part) => formatAmount(part, { prec: 3, lowest: 0, highest: 0 })).join(' + ')
}
