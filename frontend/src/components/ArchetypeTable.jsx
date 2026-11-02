import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from './Async.jsx'

const pct = (x) => (x == null ? '—' : `${(x * 100).toFixed(0)}%`)

export function ArchetypeTable() {
  const [k, setK] = useState(5)
  const state = useAsync(() => api.archetypes(k), [k])

  return (
    <div className="panel">
      <h2>Winning roster archetypes</h2>
      <p className="sub">K-means on team-season spending profiles, scored by how often each cluster reaches / wins the Super Bowl.</p>

      <div className="controls">
        <div>
          <label className="field">Clusters (k)</label>
          <select value={k} onChange={(e) => setK(Number(e.target.value))}>
            {[3, 4, 5, 6, 7, 8].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
      </div>

      <Async state={state}>
        {(d) => (
          <table>
            <thead>
              <tr>
                <th>Archetype</th>
                <th className="num">Team-seasons</th>
                <th className="num">SB appearance</th>
                <th className="num">SB win</th>
              </tr>
            </thead>
            <tbody>
              {d.success.map((r) => (
                <tr key={r.archetype}>
                  <td>{r.label}</td>
                  <td className="num">{r.n_team_seasons}</td>
                  <td className="num">{pct(r.sb_appearance_rate)}</td>
                  <td className="num">{pct(r.sb_win_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Async>
    </div>
  )
}
