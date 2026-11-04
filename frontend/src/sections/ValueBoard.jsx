import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'
import { Field } from '../components/Field.jsx'
import { PosTag } from '../components/PosTag.jsx'

const GRADE_COLOR = {
  A: 'var(--pay)', B: '#5fce89', C: '#e0b54a', D: 'var(--value)', F: '#e5604d',
}

function Grade({ g }) {
  const base = String(g || '').charAt(0)
  const color = GRADE_COLOR[base] || 'var(--ink-dim)'
  return <span className="grade" style={{ color, background: `${color}22` }}>{g}</span>
}

function Stars({ n }) {
  const v = Math.max(0, Math.min(5, Number(n) || 0))
  return (
    <span className="stars" aria-label={`${v} of 5`}>
      <span className="on">{'★'.repeat(v)}</span>
      <span className="off">{'★'.repeat(5 - v)}</span>
    </span>
  )
}

function Board({ title, rows }) {
  return (
    <div className="card">
      <div className="section-head"><h2>{title}</h2></div>
      {!rows?.length ? <p className="muted">No players to show.</p> : (
        <div className="table-scroll">
          <table className="dtable">
            <thead>
              <tr>
                <th>Player</th><th>Team</th><th>Pos</th>
                <th className="num">OVR</th><th>Grade</th>
                <th className="num">$/yr</th><th className="num">Value idx</th><th>Value</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.player}-${i}`}>
                  <td>{r.player}</td>
                  <td className="muted">{r.team}</td>
                  <td><PosTag pos={r.pos_group} /></td>
                  <td className="num">{r.madden_ovr}</td>
                  <td><Grade g={r.grade} /></td>
                  <td className="num">${Number(r.apy).toFixed(1)}M</td>
                  <td className="num">{r.value_index > 0 ? '+' : ''}{r.value_index}</td>
                  <td><Stars n={r.value} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export function ValueBoard() {
  const [position, setPosition] = useState('All')
  const [positions, setPositions] = useState(['All'])
  const state = useAsync(() => api.valueBoard(position), [position])

  useEffect(() => {
    if (state.data?.positions) setPositions(state.data.positions)
  }, [state.data])

  return (
    <div className="wrap">
      <div className="lede">
        <div className="eyebrow">Value Board</div>
        <h1>The best and worst contracts in football.</h1>
        <p>
          The value index pits a player's caliber percentile against his pay percentile at the
          same position — positive means more production per dollar than the market demands.
        </p>
      </div>

      <div className="block card">
        <div className="controls">
          <Field label="Position" value={position} onChange={setPosition} options={positions} width={170} />
        </div>
      </div>

      <Async state={state}>
        {(d) => (
          <>
            <div className="block"><Board title={`Best values${position === 'All' ? '' : ` — ${position}`}`} rows={d.best} /></div>
            <div className="block"><Board title="Biggest overpays" rows={d.worst} /></div>
          </>
        )}
      </Async>
    </div>
  )
}
