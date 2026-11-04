import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from './Async.jsx'
import { Field } from './Field.jsx'
import { PosTag, POS_COLOR } from './PosTag.jsx'
import { pct, usd } from '../lib/format.js'

export function TeamExplorer({ meta }) {
  const [team, setTeam] = useState(meta.teams[0])
  const [season, setSeason] = useState(
    meta.seasons.includes(meta.current_season) ? meta.current_season : meta.seasons[0],
  )
  const state = useAsync(() => api.teamSeason(team, Number(season)), [team, season])

  return (
    <div className="card">
      <div className="section-head">
        <h2>Team spending profile</h2>
        <p className="sub">Where a team's cap actually goes, and the contracts driving it.</p>
      </div>

      <div className="controls" style={{ marginBottom: 20 }}>
        <Field label="Team" value={team} onChange={setTeam} options={meta.teams} />
        <Field label="Season" value={season} onChange={setSeason} options={meta.seasons.map(String)} />
      </div>

      <Async state={state} empty={`No cap data for ${team} ${season}.`}>
        {(d) => {
          const max = Math.max(...d.positions.map((p) => p.cap_pct_norm || 0), 0.01)
          return (
            <div className="split">
              <div>
                <div className="list-title">By position group</div>
                <div className="rows">
                  {d.positions.map((p) => (
                    <div className="share-row" key={p.pos_group}>
                      <div className="pos"><PosTag pos={p.pos_group} /></div>
                      <div className="share-track">
                        <div className="share-fill" style={{ width: `${((p.cap_pct_norm || 0) / max) * 100}%`, background: POS_COLOR[p.pos_group] || '#8b909b' }} />
                      </div>
                      <div className="usd">{pct(p.cap_pct_norm)}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div className="list-title">Biggest contracts</div>
                {d.players.slice(0, 11).map((p, i) => (
                  <div className="contract" key={i}>
                    <span className="who">{p.player}</span>
                    <span className="tag">{p.position}</span>
                    <span className="amt">{usd(p.cap_number)}</span>
                  </div>
                ))}
              </div>
            </div>
          )
        }}
      </Async>
    </div>
  )
}
