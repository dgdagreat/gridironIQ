// Shared number formatting for the UI.
export const pct = (x, d = 1) => (x == null || Number.isNaN(x) ? '—' : `${(x * 100).toFixed(d)}%`)

export const signedPct = (x, d = 2) =>
  x == null || Number.isNaN(x) ? '—' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(d)}%`

export const usd = (x) => {
  if (x == null || Number.isNaN(x)) return '—'
  if (Math.abs(x) >= 1e6) return `$${(x / 1e6).toFixed(1)}M`
  if (Math.abs(x) >= 1e3) return `$${(x / 1e3).toFixed(0)}K`
  return `$${x.toFixed(0)}`
}

export const num = (x, d = 2) => (x == null || Number.isNaN(x) ? '—' : Number(x).toFixed(d))
