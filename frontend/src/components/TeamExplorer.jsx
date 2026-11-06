import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from './Async.jsx'
import { Field } from './Field.jsx'
import { PosTag, POS_COLOR } from './PosTag.jsx'
import { pct, usd } from '../lib/format.js'
import { defaultSeason } from '../lib/positions.js'
import { CapGauge } from './CapGauge.jsx'
import { SpendingDonut } from './SpendingDonut.jsx'
import { BlueprintRadar } from './BlueprintRadar.jsx'
import { BlueprintGap } from './BlueprintGap.jsx'
import { EpaPanel } from './EpaPanel.jsx'

// The Boardroom's deep dive on one team-season: the cap gauge, the position ↔
// player breakdown with an offense/defense donut, the Super Bowl champion
// blueprint comparison (radar + gap), and on-field EPA. Opens on the current
// (2026) season and rolls forward on its own.
export function TeamExplorer({ meta, premium }) {
  const [team, setTeam] = useState(meta.teams.includes('KC') ? 'KC' : meta.teams[0])
  const [season, setSeason] = useState(defaultSeason(meta))
  const [view, setView] = useState('position') // 'position' | 'player'
  const [playerN, setPlayerN] = useState(16)
  const state = useAsync(() => api.teamSeason(team, Number(season)), [team, season])

  return (
    <div className="card">
      <div className="section-head">
        <h2>Team spending profile</h2>
        <p className="sub">Where a team's cap actually goes, how it stacks up against the Super Bowl champion blueprint, and whether it translated on the field.</p>
      </div>

      <div className="controls" style={{ marginBottom: 20 }}>
        <Field label="Team" value={team} onChange={setTeam} options={meta.teams} />
        <Field label="Season" value={season} onChange={setSeason} options={meta.seasons.map(String)} />
      </div>

      <Async state={state} empty={`No cap data for ${team} ${season}.`}>
        {(d) => {
          const committed = d.positions.reduce((s, p) => s + (p.cap_dollars || 0), 0)
          const maxPos = Math.max(...d.positions.map((p) => p.cap_pct_norm || 0), 0.01)
          const top = d.players.slice(0, playerN)
          const maxPlayer = Math.max(...top.map((p) => p.cap_number || 0), 1)
          return (
            <>
              <CapGauge committed={committed} cap={d.league_cap} season={d.season} currentSeason={meta.current_season} />

              <div className="seg" style={{ margin: '18px 0 16px' }}>
                <button className={view === 'position' ? 'active' : ''} onClick={() => setView('position')}>By position group</button>
                <button className={view === 'player' ? 'active' : ''} onClick={() => setView('player')}>By individual player</button>
              </div>

              <div className="split">
                <div>
                  {view === 'position' ? (
                    <>
                      <div className="list-title">Cap share by position group</div>
                      <div className="rows">
                        {d.positions.map((p) => (
                          <div className="share-row" key={p.pos_group}>
                            <div className="pos"><PosTag pos={p.pos_group} /></div>
                            <div className="share-track">
                              <div className="share-fill" style={{ width: `${((p.cap_pct_norm || 0) / maxPos) * 100}%`, background: POS_COLOR[p.pos_group] || 'var(--accent)' }} />
                            </div>
                            <div className="usd">{pct(p.cap_pct_norm)}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="list-title list-title-row">
                        <span>Cap hit by player (top {top.length})</span>
                        {d.players.length > 10 && (
                          <input type="range" min="10" max={Math.min(40, d.players.length)} value={playerN}
                            onChange={(e) => setPlayerN(Number(e.target.value))} aria-label="How many players" />
                        )}
                      </div>
                      <div className="rows">
                        {top.map((p, i) => (
                          <div className="share-row player" key={i} title={`${p.player} · ${p.position} · ${usd(p.cap_number)}`}>
                            <div className="pos name">{p.player}</div>
                            <div className="share-track">
                              <div className="share-fill" style={{ width: `${((p.cap_number || 0) / maxPlayer) * 100}%`, background: 'var(--accent)' }} />
                            </div>
                            <div className="usd">{usd(p.cap_number)}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  )}
                </div>
                <div className="donut-wrap"><SpendingDonut positions={d.positions} team={team} /></div>
              </div>

              <div className="blueprint">
                <div className="list-title" style={{ marginTop: 30 }}>{team} {season} vs. the Super Bowl champion blueprint</div>
                <p className="hint" style={{ margin: '0 0 14px' }}>
                  Your normalized cap share at each position vs. what Super Bowl winners have averaged there. The radar overlays the two spending shapes; the bar breaks out the gap.
                </p>
                <Async state={premium}>
                  {(prem) => (
                    <div className="split">
                      <BlueprintRadar positions={d.positions} premium={prem} team={team} season={season} />
                      <BlueprintGap positions={d.positions} premium={prem} />
                    </div>
                  )}
                </Async>
              </div>

              <EpaPanel epa={d.epa} team={team} season={season} />
            </>
          )
        }}
      </Async>
    </div>
  )
}
