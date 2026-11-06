import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from './Async.jsx'
import { Field } from './Field.jsx'
import { POS_ORDER, POS_UNIT, defaultSeason } from '../lib/positions.js'

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

// Round to a clean axis with ~5 evenly spaced ticks that hug the data, so the
// scale reads in tidy percentages (…, 15%, 20%, 25%) without wasting half the
// width on empty headroom.
function niceScale(m) {
  const raw = m / 5
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const norm = raw / mag
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag
  const top = Math.ceil(m / step - 1e-9) * step
  const ticks = []
  for (let t = 0; t <= top + 1e-9; t += step) ticks.push(+t.toFixed(10))
  return { ticks }
}

const fmtTick = (t) => `${+(t * 100).toFixed(1)}%`

// Horizontal dumbbell/dot plot: one row per position, a connector spanning the
// lowest-to-highest team so the spread reads at a glance, and a dot per team on
// a shared percentage axis. Rows are grouped offense / defense / special teams.
function CompareChart({ data }) {
  const series = data.map((d, i) => ({
    team: d.team,
    color: SERIES[i % SERIES.length],
    map: new Map(d.positions.map((p) => [p.pos_group, p.cap_pct_norm])),
  }))
  const order = POS_ORDER.filter((p) => series.some((s) => s.map.has(p)))
  const rawMax = Math.max(...series.flatMap((s) => [...s.map.values()]), 0.01)
  const { ticks } = niceScale(rawMax)
  const max = ticks[ticks.length - 1]

  // Geometry (SVG user units; the viewBox scales to the container width).
  const W = 640, PAD_L = 46, PAD_R = 14, PAD_T = 6, AXIS_H = 26, RH = 30, GH = 26
  const x0 = PAD_L, x1 = W - PAD_R
  const xs = (v) => x0 + (v / max) * (x1 - x0)

  // Interleave unit headers with position rows and lay everything out top-down.
  let lastUnit = null, y = PAD_T
  const laid = []
  for (const p of order) {
    const u = POS_UNIT[p]
    if (u !== lastUnit) { laid.push({ group: u, y }); y += GH; lastUnit = u }
    laid.push({ pos: p, y, cy: y + RH / 2 }); y += RH
  }
  const plotBottom = y
  const H = plotBottom + AXIS_H

  return (
    <div>
      <div className="cmp-legend">
        {series.map((s) => <span key={s.team}><i style={{ background: s.color }} />{s.team}</span>)}
      </div>
      <svg className="cmp-svg" viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label="Cap share by position for the selected teams">
        {/* gridlines + axis ticks */}
        {ticks.map((t) => (
          <g key={t}>
            <line x1={xs(t)} x2={xs(t)} y1={PAD_T} y2={plotBottom}
              className={t === 0 ? 'cmp-grid cmp-axisline' : 'cmp-grid'} />
            <text x={xs(t)} y={plotBottom + 17} className="cmp-axis" textAnchor="middle">{fmtTick(t)}</text>
          </g>
        ))}

        {laid.map((it) =>
          it.group ? (
            <text key={`g-${it.group}`} x={0} y={it.y + 16} className="cmp-group">{it.group}</text>
          ) : (
            <g key={it.pos}>
              <text x={PAD_L - 10} y={it.cy} className="cmp-lbl" textAnchor="end" dominantBaseline="middle">{it.pos}</text>
              {(() => {
                const vals = series.map((s) => s.map.get(it.pos)).filter((v) => v != null)
                if (!vals.length) return null
                const lo = Math.min(...vals), hi = Math.max(...vals)
                return <line x1={xs(lo)} x2={xs(hi)} y1={it.cy} y2={it.cy} className="cmp-connect" />
              })()}
              {series.map((s) => {
                const v = s.map.get(it.pos)
                if (v == null) return null
                return (
                  <circle key={s.team} className="cmp-pt" cx={xs(v)} cy={it.cy} r={5.5} fill={s.color}>
                    <title>{`${s.team} · ${it.pos}: ${(v * 100).toFixed(1)}% of cap`}</title>
                  </circle>
                )
              })}
            </g>
          ),
        )}
      </svg>
    </div>
  )
}
