import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'

function PlayerTable({ rows, columns }) {
  if (!rows?.length) return <p className="muted">No players to show.</p>
  return <div className="table-scroll"><table>
    <thead><tr>{columns.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead>
    <tbody>{rows.map((row, i) => <tr key={`${row.player}-${i}`}>
      {columns.map(([key]) => <td key={key}>{row[key] == null ? '—' : row[key]}</td>)}
    </tr>)}</tbody>
  </table></div>
}

const gradeColor = (score) => {
  const n = Number(score)
  return n >= 85 ? '#1a7f37' : n >= 70 ? '#3fb950' : n >= 45 ? '#bf8700' : n >= 25 ? '#d4691e' : '#cf222e'
}

function FootballField({ starters, mode }) {
  const lines = [35, 40, 45, 50, 55, 60, 65]
  return <div className="field-wrap">
    <svg className="football-field" viewBox="0 0 533 350" role="img" aria-label="Projected 11-personnel offense versus nickel defense">
      <rect x="0" y="0" width="533" height="350" rx="9" fill="#2f8f4e" />
      {lines.map((yard) => <g key={yard}>
        <line x1="0" x2="533" y1={(66-yard)*10} y2={(66-yard)*10} stroke="rgba(255,255,255,.3)" strokeWidth={yard % 10 === 0 ? 2 : 1} />
        {yard % 10 === 0 && <><text x="7" y={(66-yard)*10-3} className="yard-mark">{yard}</text><text x="508" y={(66-yard)*10-3} className="yard-mark">{yard}</text></>}
      </g>)}
      <line x1="0" x2="533" y1={(66-44)*10} y2={(66-44)*10} stroke="rgba(255,255,255,.88)" strokeWidth="2" />
      <text x="266" y="31" textAnchor="middle" className="field-label">▲ DEFENSE · NICKEL</text>
      <text x="266" y="340" textAnchor="middle" className="field-label">▼ OFFENSE · 11 PERSONNEL</text>
      {starters.map((slot, i) => {
        const grade = mode === 'unit' ? slot.strength : slot.grade_pct
        const cx = slot.x * 10
        const cy = (66-slot.y) * 10
        const color = slot.player ? gradeColor(grade ?? slot.strength) : '#6b7280'
        return <g key={`${slot.label}-${i}`}>
          <title>{slot.player ? `${slot.player} · ${slot.label} (${slot.pos_group}) · OVR ${slot.madden_ovr ?? '—'} · ${mode === 'unit' ? 'unit' : 'player'} grade ${Math.round(grade ?? slot.strength)} · unit rank ${slot.rank}/${slot.n_teams}` : `${slot.label} · no starter listed`}</title>
          <rect x={cx-15} y={cy-13} width="30" height="26" rx="4" fill={color} stroke="#fff" strokeWidth="1.4" />
          <text x={cx} y={cy+3} textAnchor="middle" className="slot-label">{slot.label}</text>
          {slot.player && <text x={cx} y={cy+24} textAnchor="middle" className="player-label">{slot.player.length > 14 ? `${slot.player.slice(0,12)}…` : slot.player}</text>}
        </g>
      })}
    </svg>
    <div className="field-legend"><span><i style={{background:'#1a7f37'}} />Strong</span><span><i style={{background:'#bf8700'}} />Average</span><span><i style={{background:'#cf222e'}} />Weak</span></div>
  </div>
}

export function Maxer({ meta }) {
  const [team, setTeam] = useState('KC')
  const [signed, setSigned] = useState([])
  const [traded, setTraded] = useState([])
  const [mode, setMode] = useState('player')
  const state = useAsync(() => api.maxer(team), [team])
  const simulation = useAsync(() => api.maxerSimulate(team, signed, traded),
    [team, signed.join('|'), traded.join('|')])
  const toggle = (list, setList, value) => setList((xs) => xs.includes(value)
    ? xs.filter((x) => x !== value) : [...xs, value])
  return <div className="page">
    <section className="panel">
      <h2>How far is each team from a champion-caliber roster?</h2>
      <p className="sub">Roster strength and this season’s results inform the outlook. Free agents and trade targets are ranked against this team’s biggest roster needs.</p>
      <div className="controls"><div>
        <label className="field" htmlFor="maxer-team">Team</label>
        <select id="maxer-team" value={team} onChange={(e) => { setTeam(e.target.value); setSigned([]); setTraded([]) }}>
          {meta.teams.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div></div>
      <Async state={state}>{({ league }) => <>
        <Async state={simulation}>{({ report, readiness_delta, starters }) => <>
        <div className="stat-grid">
          <div className="stat"><div className="label">SB outlook</div><div className="value">{report.readiness.toFixed(1)}<small>/100</small></div>{(signed.length || traded.length) > 0 && <div className="delta">{readiness_delta >= 0 ? '+' : ''}{readiness_delta} vs. base</div>}</div>
          <div className="stat"><div className="label">Roster</div><div className="value">{report.roster_readiness.toFixed(0)}</div></div>
          <div className="stat"><div className="label">Organization</div><div className="value">{report.org_score.toFixed(0)}</div></div>
          <div className="stat"><div className="label">Predicted rank</div><div className="value">#{report.rank}<small> / {report.n_teams}</small></div></div>
        </div>
        <p className="muted">Biggest needs: {report.top_needs.join(', ') || '—'}{report.season_record ? ` · ${report.season_record.wins}–${report.season_record.losses}–${report.season_record.ties} this season` : ''}</p>
        <div className="field-heading"><h3>Projected starters · 11 personnel vs. nickel</h3><div className="mode-toggle" aria-label="Shade field by">{[['player','Individual'],['unit','Unit grade']].map(([value,label]) => <button key={value} className={mode === value ? 'active' : ''} onClick={() => setMode(value)}>{label}</button>)}</div></div>
        <FootballField starters={starters} mode={mode} />
        <div className="row">
          <div><h3>Position needs</h3><PlayerTable rows={report.needs} columns={[["pos_group", "Position"], ["strength", "Strength"], ["blueprint", "Blueprint"], ["gap", "Gap"]]} /></div>
          <div><h3>League outlook</h3><PlayerTable rows={league.slice(0, 8)} columns={[["rank", "#"], ["team", "Team"], ["outlook", "Outlook"]]} /></div>
        </div>
        </>}</Async>
      </>}</Async>
    </section>
    <section className="panel"><h2>Build your team</h2><p className="sub">Select players to sign or trade for. Each selection recomputes the roster, starter field, unit grades and outlook.</p>
      <Async state={state}>{({ free_agents, trade_targets }) => <div className="row">
        <div><h3>🟢 Free agents</h3><div className="pick-list">{free_agents.map((p) => <button className={`pick-row ${signed.includes(p.player) ? 'selected' : ''}`} key={p.player} disabled={!signed.includes(p.player) && signed.length + traded.length >= 12} onClick={() => toggle(signed, setSigned, p.player)}><span><b>{p.player}</b><small>{p.pos_group} · age {Number(p.age).toFixed(0)} · OVR {p.madden_ovr}</small></span><span>${Number(p.est_apy || 0).toFixed(1)}M/yr</span><em>{signed.includes(p.player) ? 'Signed ✓' : 'Sign +'}</em></button>)}</div></div>
        <div><h3>🔄 Trade targets</h3><div className="pick-list">{trade_targets.map((p) => <button className={`pick-row ${traded.includes(p.gsis_id) ? 'selected' : ''}`} key={p.gsis_id} disabled={!traded.includes(p.gsis_id) && signed.length + traded.length >= 12} onClick={() => toggle(traded, setTraded, p.gsis_id)}><span><b>{p.player}</b><small>{p.team} · {p.pos_group} · age {Number(p.age).toFixed(0)}</small></span><span>{p.pick_tier}</span><em>{traded.includes(p.gsis_id) ? 'Added ✓' : 'Trade +'}</em></button>)}</div></div>
      </div>}</Async>
      {(signed.length > 0 || traded.length > 0) && <p className="move-summary">Selected {signed.length + traded.length} move{signed.length + traded.length === 1 ? '' : 's'}{signed.length > 0 ? ` · estimated free-agent APY $${Number(state.data?.free_agents.filter((p) => signed.includes(p.player)).reduce((sum, p) => sum + Number(p.est_apy || 0), 0)).toFixed(1)}M` : ''}{traded.length > 0 ? ` · ${traded.length} trade pick estimate${traded.length === 1 ? '' : 's'} shown above` : ''}</p>}
      {(signed.length > 0 || traded.length > 0) && <button className="secondary" onClick={() => { setSigned([]); setTraded([]) }}>Reset moves</button>}
    </section>
  </div>
}
