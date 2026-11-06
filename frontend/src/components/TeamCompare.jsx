import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from './Async.jsx'
import { Field } from './Field.jsx'
import { POS_ORDER, defaultSeason } from '../lib/positions.js'

const SERIES = ['var(--accent)', 'var(--pay)', 'var(--value)', '#c084fc', '#f472b6', '#34d3d3']
const DIV_PLACEHOLDER = 'Load a division…'

// Head-to-head: normalized cap share by position for up to six teams, as a
// dot plot (each team a colored marker per position row). Opens on the current
// season and a full division so there's something to read immediately.
export function TeamCompare({ meta }) {
  const [season, setSeason] = useState(defaultSeason(meta))
  const firstDivision = Object.values(meta.divisions || {})[0] || meta.teams.slice(0, 4)
  const [teams, setTeams] = useState(() => firstDivision.filter((t) => meta.teams.includes(t)))

  const toggle = (t) =>
    setTeams((cur) =>
      cur.includes(t) ? cur.filter((x) => x !== t) : cur.length >= 6 ? cur : [...cur, t])
  const loadDivision = (d) => {
    const members = meta.divisions?.[d]
    if (members) setTeams(members.filter((t) => meta.teams.includes(t)))
  }

  const state = useAsync(
    () => (teams.length ? api.compare(Number(season), teams) : Promise.resolve([])),
    [season, teams.join(',')],
  )

  return (
    <div className="card">
      <div className="section-head">
        <h2>Compare cap efficiency</h2>
        <p className="sub">Normalized cap share by position for up to six teams. Load a division, or toggle teams below.</p>
      </div>

      <div className="controls" style={{ marginBottom: 14 }}>
        <Field label="Season" value={season} onChange={setSeason} options={meta.seasons.map(String)} />
        <Field label="Division preset" value={DIV_PLACEHOLDER} onChange={loadDivision}
          options={[DIV_PLACEHOLDER, ...Object.keys(meta.divisions || {})]} />
      </div>

      <div className="chips">
        {meta.teams.map((t) => {
          const on = teams.includes(t)
          return (
            <button key={t} className={`chip ${on ? 'on' : ''}`} onClick={() => toggle(t)}
              disabled={!on && teams.length >= 6}>{t}</button>
          )
        })}
      </div>

      <Async state={state} empty="Pick at least one team to compare.">
        {(data) => <CompareChart data={data} />}
      </Async>
    </div>
  )
}

function CompareChart({ data }) {
  const series = data.map((d, i) => ({
    team: d.team,
    color: SERIES[i % SERIES.length],
    map: new Map(d.positions.map((p) => [p.pos_group, p.cap_pct_norm])),
  }))
  const order = POS_ORDER.filter((p) => series.some((s) => s.map.has(p)))
  const max = Math.max(...series.flatMap((s) => [...s.map.values()]), 0.01)

  return (
    <div>
      <div className="cmp-legend">
        {series.map((s) => <span key={s.team}><i style={{ background: s.color }} />{s.team}</span>)}
      </div>
      <div className="cmp">
        {order.map((p) => (
          <div className="cmp-row" key={p}>
            <div className="cmp-pos">{p}</div>
            <div className="cmp-track">
              {series.map((s) => {
                const v = s.map.get(p)
                if (v == null) return null
                return (
                  <span key={s.team} className="cmp-dot"
                    style={{ left: `${(v / max) * 100}%`, background: s.color }}
                    title={`${s.team} · ${p}: ${(v * 100).toFixed(1)}% of cap`} />
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
