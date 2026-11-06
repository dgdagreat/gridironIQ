import { usd } from '../lib/format.js'

// Bullet gauge: how much of the league cap a team has committed, with the cap
// limit marked at 100%. Green under the cap, amber as it tightens, red over.
// Future (projection) seasons show only cap already tied up on signed deals.
export function CapGauge({ committed, cap, season, currentSeason }) {
  if (!cap) return null
  const pct = (100 * committed) / cap
  const axisMax = Math.max(110, pct + 8)
  const color = pct > 100 ? 'var(--brand)' : pct >= 92 ? 'var(--value)' : 'var(--pay)'
  const label = season <= currentSeason ? 'Cap committed' : 'Cap committed (future)'
  return (
    <div className="gauge">
      <div className="gauge-head">
        <span className="k">{label}</span>
        <span className="val" style={{ color }}>{pct.toFixed(0)}%</span>
      </div>
      <div className="gauge-track">
        <div className="gauge-fill" style={{ width: `${Math.min(100, (pct / axisMax) * 100)}%`, background: color }} />
        <div className="gauge-threshold" style={{ left: `${(100 / axisMax) * 100}%` }} title="Salary cap (100%)" />
      </div>
      <div className="gauge-sub">{usd(committed)} of the {usd(cap)} cap · limit marked at 100%</div>
    </div>
  )
}
