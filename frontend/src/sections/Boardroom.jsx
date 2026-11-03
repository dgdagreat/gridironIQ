import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'
import { PremiumChart } from '../components/PremiumChart.jsx'
import { VerdictTable } from '../components/VerdictTable.jsx'
import { TeamExplorer } from '../components/TeamExplorer.jsx'
import { Archetypes } from '../components/Archetypes.jsx'

export function Boardroom({ meta }) {
  const premium = useAsync(() => api.championPremium(), [])
  const verdict = useAsync(() => api.efficiencyVerdict(), [])

  return (
    <div className="wrap">
      <div className="lede">
        <div className="eyebrow">The cap-efficiency thesis</div>
        <h1>Champions don't spend more.<br />They spend it differently.</h1>
        <p>
          Across the salary-cap era, Super Bowl winners don't out-spend the league — they
          tilt the cap toward a handful of positions and find value in the rest. Here's where
          the money actually moves.
        </p>
      </div>

      <div className="block card">
        <div className="section-head">
          <h2>Where Super Bowl winners overspend</h2>
          <p className="sub">Champion cap share at each position minus the league average, in percentage points of the cap.</p>
        </div>
        <div className="split" style={{ gridTemplateColumns: '1.35fr 1fr' }}>
          <Async state={premium}>{(d) => <PremiumChart data={d} />}</Async>
          <Async state={verdict}>{(d) => <VerdictTable data={d} />}</Async>
        </div>
      </div>

      <div className="block"><TeamExplorer meta={meta} /></div>
      <div className="block"><Archetypes /></div>
    </div>
  )
}
