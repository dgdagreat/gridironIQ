import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from './Async.jsx'
import { Field } from './Field.jsx'
import { pct } from '../lib/format.js'

export function Archetypes() {
  const [k, setK] = useState('5')
  const state = useAsync(() => api.archetypes(Number(k)), [k])

  return (
    <div className="card">
      <div className="section-head">
        <h2>Winning roster archetypes</h2>
        <p className="sub">K-means over team-season spending profiles, ranked by how often each cluster reaches and wins the Super Bowl.</p>
      </div>

      <div className="controls" style={{ marginBottom: 20 }}>
        <Field label="Clusters" value={k} onChange={setK} options={['3', '4', '5', '6', '7', '8']} />
      </div>

      <Async state={state}>
        {(d) => {
          const maxWin = Math.max(...d.success.map((r) => r.sb_win_rate || 0), 0.01)
          return (
            <div className="arch-grid">
              {d.success.map((r) => (
                <div className="arch" key={r.archetype}>
                  <div className="label">{r.label}</div>
                  <div className="n">{r.n_team_seasons} team-seasons</div>
                  <div className="meter"><i style={{ width: `${((r.sb_win_rate || 0) / maxWin) * 100}%` }} /></div>
                  <div className="rates">
                    <span>SB app <b>{pct(r.sb_appearance_rate, 0)}</b></span>
                    <span>win <b>{pct(r.sb_win_rate, 0)}</b></span>
                  </div>
                </div>
              ))}
            </div>
          )
        }}
      </Async>
    </div>
  )
}
