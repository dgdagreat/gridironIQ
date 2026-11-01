import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'
import { ChampionPremiumChart } from '../components/ChampionPremiumChart.jsx'
import { EfficiencyVerdictTable } from '../components/EfficiencyVerdictTable.jsx'
import { TeamSpendingExplorer } from '../components/TeamSpendingExplorer.jsx'
import { ArchetypeTable } from '../components/ArchetypeTable.jsx'

export function Boardroom({ meta }) {
  const premium = useAsync(() => api.championPremium(), [])
  const verdict = useAsync(() => api.efficiencyVerdict(), [])

  return (
    <div className="page">
      <div className="panel">
        <h2>Do champions over- or under-pay by position?</h2>
        <p className="sub">
          Average positional cap share among Super Bowl winners minus the league average, since the salary-cap era.
          Green = champions pay up; orange = they win spending less.
        </p>
        <div className="row">
          <div style={{ flex: '2 1 440px' }}>
            <Async state={premium}>
              {(d) => <ChampionPremiumChart data={d} />}
            </Async>
          </div>
          <div style={{ flex: '1 1 340px' }}>
            <Async state={verdict}>
              {(d) => <EfficiencyVerdictTable data={d} />}
            </Async>
          </div>
        </div>
      </div>

      <TeamSpendingExplorer meta={meta} />
      <ArchetypeTable />
    </div>
  )
}
