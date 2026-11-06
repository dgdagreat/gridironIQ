import { useRef, useState } from 'react'
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

// Spread a row's dots vertically wherever they'd otherwise overlap, so clusters
// read as a tidy little column (beeswarm) instead of a blurry blob.
function dodge(points) {
  const MINGAP = 14, MAXEXT = 10
  const sorted = [...points].sort((a, b) => a.x - b.x)
  const clusters = []
  for (const p of sorted) {
    const last = clusters[clusters.length - 1]
    if (last && p.x - last[last.length - 1].x < MINGAP) last.push(p)
    else clusters.push([p])
  }
  const out = []
  for (const c of clusters) {
    const n = c.length
    const spread = n > 1 ? Math.min(9, (2 * MAXEXT) / (n - 1)) : 0
    c.forEach((p, i) => out.push({ ...p, dy: (i - (n - 1) / 2) * spread }))
  }
  return out
}

// Horizontal dumbbell/dot plot: one row per position, a connector spanning the
// lowest-to-highest team so the spread reads at a glance, and a dot per team on
// a shared percentage axis. Rows group offense / defense / special teams. Hover
// a dot or a legend team to trace it across every row; hovering a row lifts it.
function CompareChart({ data }) {
  const wrapRef = useRef(null)
  const [lit, setLit] = useState(null) // highlighted team (legend / dot hover)
  const [tip, setTip] = useState(null) // { left, top, team, color, pos, val }

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
  const W = 640, PAD_L = 46, PAD_R = 16, PAD_T = 6, AXIS_H = 26, RH = 32, GH = 26, R = 5
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

  const show = (e, team, color, pos, val) => {
    const r = wrapRef.current?.getBoundingClientRect()
    if (!r) return
    setLit(team)
    setTip({ left: e.clientX - r.left, top: e.clientY - r.top, team, color, pos, val })
  }
  const clear = () => { setLit(null); setTip(null) }

  return (
    <div className="cmp-wrap" ref={wrapRef}>
      <div className="cmp-legend">
        {series.map((s) => (
          <span key={s.team} className={lit && lit !== s.team ? 'off' : ''}
            onMouseEnter={() => setLit(s.team)} onMouseLeave={() => setLit(null)}>
            <i style={{ background: s.color }} />{s.team}
          </span>
        ))}
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

        {laid.map((it) => {
          if (it.group) return <text key={`g-${it.group}`} x={0} y={it.y + 16} className="cmp-group">{it.group}</text>
          const pts = dodge(
            series
              .map((s) => ({ team: s.team, color: s.color, v: s.map.get(it.pos) }))
              .filter((p) => p.v != null)
              .map((p) => ({ ...p, x: xs(p.v) })),
          )
          if (!pts.length) return null
          const vals = pts.map((p) => p.x)
          const lo = Math.min(...vals), hiX = Math.max(...vals)
          return (
            <g key={it.pos} className="cmp-rowg">
              <rect className="cmp-band" x={0} y={it.cy - RH / 2} width={W} height={RH} />
              <text x={PAD_L - 12} y={it.cy} className="cmp-lbl" textAnchor="end" dominantBaseline="middle">{it.pos}</text>
              <line x1={lo} x2={hiX} y1={it.cy} y2={it.cy} className="cmp-connect"
                style={{ opacity: lit ? 0.35 : 1 }} />
              {pts.map((p) => (
                <circle key={p.team} className="cmp-pt" cx={p.x} cy={it.cy + p.dy} r={R} fill={p.color}
                  style={{ opacity: lit && lit !== p.team ? 0.18 : 1 }}
                  onMouseEnter={(e) => show(e, p.team, p.color, it.pos, p.v)}
                  onMouseMove={(e) => show(e, p.team, p.color, it.pos, p.v)}
                  onMouseLeave={clear} />
              ))}
            </g>
          )
        })}
      </svg>

      {tip && (
        <div className="cmp-tip" style={{ left: tip.left, top: tip.top }}>
          <div className="t-team"><i style={{ background: tip.color }} />{tip.team}</div>
          <div className="t-val">{tip.pos} · {(tip.val * 100).toFixed(1)}% of cap</div>
        </div>
      )}
    </div>
  )
}
