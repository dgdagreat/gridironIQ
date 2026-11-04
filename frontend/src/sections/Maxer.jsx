import { useState, useRef } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'
import { Field } from '../components/Field.jsx'
import { PosTag } from '../components/PosTag.jsx'
import { num } from '../lib/format.js'

const gradeColor = (score) => {
  const n = Number(score)
  if (!Number.isFinite(n)) return '#5b6472'
  return n >= 85 ? '#2fbf6c' : n >= 70 ? '#5fce89' : n >= 50 ? '#e0b54a' : n >= 30 ? '#ef9a3d' : '#e5604d'
}

function FootballField({ starters, mode }) {
  const lines = [35, 40, 45, 50, 55, 60, 65]
  const wrapRef = useRef(null)
  const [hover, setHover] = useState(null)

  const track = (slot, i) => (e) => {
    if (!slot.player) return
    const r = wrapRef.current?.getBoundingClientRect()
    if (r) setHover({ i, slot, x: e.clientX - r.left, y: e.clientY - r.top })
  }

  return (
    <div className="field-wrap" ref={wrapRef}>
      <svg className="football-field" viewBox="0 0 533 350" role="img"
        aria-label="Projected 11-personnel offense versus nickel defense"
        onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="turf" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#1b4733" />
            <stop offset="1" stopColor="#123020" />
          </linearGradient>
        </defs>
        <rect x="0" y="0" width="533" height="350" rx="6" fill="url(#turf)" />
        {lines.map((yard) => (
          <line key={yard} x1="0" x2="533" y1={(66 - yard) * 10} y2={(66 - yard) * 10}
            stroke="rgba(255,255,255,.1)" strokeWidth={yard % 10 === 0 ? 1.5 : 1} />
        ))}
        <line x1="0" x2="533" y1={(66 - 44) * 10} y2={(66 - 44) * 10} stroke="rgba(255,255,255,.45)" strokeWidth="1.5" />
        <text x="266" y="31" textAnchor="middle" className="field-label">▲ DEFENSE · NICKEL</text>
        <text x="266" y="341" textAnchor="middle" className="field-label">▼ OFFENSE · 11 PERSONNEL</text>
        {starters.map((slot, i) => {
          const grade = mode === 'unit' ? slot.strength : slot.grade_pct
          const cx = slot.x * 10
          const cy = (66 - slot.y) * 10
          const color = slot.player ? gradeColor(grade ?? slot.strength) : '#5b6472'
          const name = slot.player
          const last = name ? (name.split(' ').slice(-1)[0] || name) : ''
          const short = last.length > 9 ? `${last.slice(0, 8)}…` : last
          const plateW = Math.min(48, short.length * 3.7 + 9)
          const active = hover && hover.i === i
          const dim = hover && hover.i !== i
          return (
            <g key={`${slot.label}-${i}`} className="field-slot" opacity={dim ? 0.38 : 1}
              style={{ cursor: slot.player ? 'pointer' : 'default' }}
              onMouseEnter={track(slot, i)} onMouseMove={track(slot, i)}>
              <rect x={cx - 16} y={cy - 12} width="32" height="24" rx="4" fill={color}
                stroke={active ? '#ffffff' : (slot.out ? '#e5604d' : 'rgba(255,255,255,.9)')}
                strokeWidth={active ? 2.2 : (slot.out ? 2 : 1.2)} />
              <text x={cx} y={cy + 3.5} textAnchor="middle" className="slot-label">{slot.label}</text>
              {name && (
                <>
                  <rect x={cx - plateW / 2} y={cy + 14} width={plateW} height="11" rx="3"
                    fill="rgba(6,8,11,0.78)" stroke={color} strokeWidth="0.6" />
                  <text x={cx} y={cy + 21.5} textAnchor="middle" className="player-label">{short}</text>
                </>
              )}
            </g>
          )
        })}
      </svg>

      {hover?.slot?.player && (() => {
        const s = hover.slot
        const g = Math.round((mode === 'unit' ? s.strength : s.grade_pct) ?? s.strength)
        return (
          <div className="field-tip" style={{ left: hover.x, top: hover.y }}>
            <div className="ft-head"><PosTag pos={s.pos_group} /> <b>{s.player}</b>{s.out && <em>OUT</em>}</div>
            <div className="ft-rows">
              <span>OVR <b>{s.madden_ovr ?? '—'}</b></span>
              <span>{mode === 'unit' ? 'Unit' : 'Player'} <b>{g}</b></span>
              <span>Rank <b>{s.rank}/{s.n_teams}</b></span>
            </div>
          </div>
        )
      })()}

      <div className="field-legend">
        <span><i style={{ background: '#2fbf6c' }} />Strong</span>
        <span><i style={{ background: '#e0b54a' }} />Average</span>
        <span><i style={{ background: '#e5604d' }} />Weak</span>
      </div>
    </div>
  )
}

export function Maxer({ meta }) {
  const defaultTeam = meta.teams.includes('KC') ? 'KC' : meta.teams[0]
  const [team, setTeam] = useState(defaultTeam)
  const [signed, setSigned] = useState([])
  const [traded, setTraded] = useState([])
  const [mode, setMode] = useState('player')

  const base = useAsync(() => api.maxer(team), [team])
  const hasMoves = signed.length > 0 || traded.length > 0
  const sim = useAsync(
    () => (hasMoves ? api.maxerSimulate(team, signed, traded) : Promise.resolve(null)),
    [team, signed.join('|'), traded.join('|')],
  )

  const onTeam = (t) => { setTeam(t); setSigned([]); setTraded([]) }
  const toggle = (list, set, v) => set((xs) => (xs.includes(v) ? xs.filter((x) => x !== v) : [...xs, v]))

  return (
    <div className="wrap">
      <div className="lede">
        <div className="eyebrow">Super Bowl Maxer</div>
        <h1>How far is each roster from a ring?</h1>
        <p>
          Roster strength and this season's results set each team's outlook. Free agents and
          trade targets are ranked against its biggest needs — sign or trade for them and watch
          the projection move.
        </p>
      </div>

      <div className="block card">
        <div className="controls" style={{ marginBottom: 4 }}>
          <Field label="Team" value={team} onChange={onTeam} options={meta.teams} />
        </div>

        <Async state={base}>
          {(b) => {
            const view = sim.data || b
            const r = view.report
            const starters = view.starters
            const league = view.league
            return (
              <div style={{ marginTop: 18 }}>
                <div className="tiles">
                  <div className="tile">
                    <div className="k">SB outlook</div>
                    <div className="v">{num(r.readiness, 1)}<small> /100</small></div>
                    {hasMoves && sim.data && (
                      <div className={`delta ${sim.data.readiness_delta >= 0 ? 'up' : 'down'}`}>
                        {sim.data.readiness_delta >= 0 ? '+' : ''}{sim.data.readiness_delta} vs. base
                      </div>
                    )}
                  </div>
                  <div className="tile"><div className="k">Roster</div><div className="v">{num(r.roster_readiness, 0)}</div></div>
                  <div className="tile"><div className="k">Organization</div><div className="v">{num(r.org_score, 0)}</div></div>
                  <div className="tile"><div className="k">Predicted rank</div><div className="v">#{r.rank}<small> /{r.n_teams}</small></div></div>
                </div>

                <p className="needline">
                  Biggest needs: <b>{r.top_needs?.join(', ') || '—'}</b>
                  {r.season_record ? ` · ${r.season_record.wins}–${r.season_record.losses}–${r.season_record.ties} this season` : ''}
                  {hasMoves && !sim.data && !sim.error ? ' · recomputing…' : ''}
                </p>
                {sim.error && <div className="state err">⚠ {sim.error.message}</div>}

                <div className="field-head">
                  <h3>Projected starters · 11 personnel vs. nickel</h3>
                  <div className="seg">
                    {[['player', 'Individual'], ['unit', 'Unit grade']].map(([v, label]) => (
                      <button key={v} className={mode === v ? 'active' : ''} onClick={() => setMode(v)}>{label}</button>
                    ))}
                  </div>
                </div>
                <FootballField starters={starters} mode={mode} />

                <div className="split" style={{ marginTop: 28 }}>
                  <div>
                    <div className="list-title">Position needs</div>
                    <div className="table-scroll">
                      <table className="dtable">
                        <thead><tr><th>Pos</th><th className="num">Strength</th><th className="num">Blueprint</th><th className="num">Gap</th></tr></thead>
                        <tbody>
                          {r.needs.filter((n) => n.blueprint != null).map((n) => (
                            <tr key={n.pos_group}>
                              <td><PosTag pos={n.pos_group} /></td>
                              <td className="num">{num(n.strength, 0)}</td>
                              <td className="num">{num(n.blueprint, 0)}</td>
                              <td className="num">{num(n.gap, 0)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                  <div>
                    <div className="list-title">League outlook</div>
                    <div className="table-scroll">
                      <table className="dtable">
                        <thead><tr><th className="num">#</th><th>Team</th><th className="num">Rec</th><th className="num">Outlook</th></tr></thead>
                        <tbody>
                          {league.slice(0, 8).map((t) => (
                            <tr key={t.team} style={t.team === team ? { background: 'var(--accent-soft)' } : undefined}>
                              <td className="num">{t.rank}</td>
                              <td>{t.team}</td>
                              <td className="num">{t.wins}–{t.losses}{t.ties ? `–${t.ties}` : ''}</td>
                              <td className="num">{num(t.outlook, 0)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>
            )
          }}
        </Async>
      </div>

      <div className="block card">
        <div className="section-head">
          <h2>Build your roster</h2>
          <p className="sub">Sign free agents or trade for targets — each pick recomputes the outlook, starters and grades above. Up to 12 moves.</p>
        </div>
        <Async state={base}>
          {(b) => (
            <>
              <div className="split">
                <div>
                  <div className="list-title">● Free agents</div>
                  <div className="picks">
                    {b.free_agents.map((p) => {
                      const on = signed.includes(p.player)
                      return (
                        <button key={p.player} className={`pick ${on ? 'on' : ''}`}
                          disabled={!on && signed.length + traded.length >= 12}
                          onClick={() => toggle(signed, setSigned, p.player)}>
                          <span className="p-main"><b>{p.player}</b><small>{p.pos_group} · age {num(p.age, 0)} · OVR {p.madden_ovr}</small></span>
                          <span className="p-cost">${num(p.est_apy, 1)}M/yr</span>
                          <span className="p-act">{on ? 'Signed ✓' : 'Sign +'}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
                <div>
                  <div className="list-title">⇄ Trade targets</div>
                  <div className="picks">
                    {b.trade_targets.map((p) => {
                      const on = traded.includes(p.gsis_id)
                      return (
                        <button key={p.gsis_id} className={`pick ${on ? 'on' : ''}`}
                          disabled={!on && signed.length + traded.length >= 12}
                          onClick={() => toggle(traded, setTraded, p.gsis_id)}>
                          <span className="p-main"><b>{p.player}</b><small>{p.team} · {p.pos_group} · age {num(p.age, 0)}</small></span>
                          <span className="p-cost">{p.pick_tier}</span>
                          <span className="p-act">{on ? 'Added ✓' : 'Trade +'}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
              {hasMoves && (
                <div className="moves">
                  <span><b style={{ color: 'var(--ink)' }}>{signed.length + traded.length}</b> move{signed.length + traded.length === 1 ? '' : 's'} selected
                    {signed.length ? ` · ${signed.length} signing${signed.length === 1 ? '' : 's'}` : ''}
                    {traded.length ? ` · ${traded.length} trade${traded.length === 1 ? '' : 's'}` : ''}</span>
                  <button className="btn ghost" onClick={() => { setSigned([]); setTraded([]) }}>Reset moves</button>
                </div>
              )}
            </>
          )}
        </Async>
      </div>
    </div>
  )
}
