import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from './Async.jsx'

const pct = (x) => (x == null ? '—' : `${(x * 100).toFixed(1)}%`)
const usd = (x) => (x == null ? '—' : `$${(x / 1e6).toFixed(1)}M`)

function Bar({ value, max }) {
  const w = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div style={{ background: '#2a313c', borderRadius: 4, height: 8, width: '100%' }}>
      <div style={{ background: 'var(--accent)', height: 8, width: `${w}%`, borderRadius: 4 }} />
    </div>
  )
}

export function TeamSpendingExplorer({ meta }) {
  const [team, setTeam] = useState(meta.teams[0])
  const [season, setSeason] = useState(
    meta.seasons.includes(meta.current_season) ? meta.current_season : meta.seasons[0],
  )
  const state = useAsync(() => api.teamSeason(team, season), [team, season])

  return (
    <div className="panel">
      <h2>Team spending profile</h2>
      <p className="sub">Where a team's cap goes by position group, and the biggest contracts behind it.</p>

      <div className="controls">
        <div>
          <label className="field">Team</label>
          <select value={team} onChange={(e) => setTeam(e.target.value)}>
            {meta.teams.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label className="field">Season</label>
          <select value={season} onChange={(e) => setSeason(Number(e.target.value))}>
            {meta.seasons.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <Async state={state} empty={`No cap data for ${team} ${season}.`}>
        {(d) => {
          const maxShare = Math.max(...d.positions.map((p) => p.cap_pct_norm || 0))
          return (
            <div className="row">
              <div>
                <table>
                  <thead>
                    <tr>
                      <th>Position</th>
                      <th className="num">Share</th>
                      <th style={{ width: '32%' }} />
                      <th className="num">Cap $</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.positions.map((p) => (
                      <tr key={p.pos_group}>
                        <td>{p.pos_group}</td>
                        <td className="num">{pct(p.cap_pct_norm)}</td>
                        <td><Bar value={p.cap_pct_norm || 0} max={maxShare} /></td>
                        <td className="num">{usd(p.cap_dollars)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <table>
                  <thead>
                    <tr>
                      <th>Top contracts</th>
                      <th>Pos</th>
                      <th className="num">Cap $</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.players.slice(0, 12).map((p, i) => (
                      <tr key={i}>
                        <td>{p.player}</td>
                        <td>{p.position}</td>
                        <td className="num">{usd(p.cap_number)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        }}
      </Async>
    </div>
  )
}
