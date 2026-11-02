import { useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'

function Board({ rows, title }) {
  return <section className="panel"><h2>{title}</h2><div className="table-scroll"><table>
    <thead><tr><th>Player</th><th>Team</th><th>Pos</th><th>OVR</th><th>Grade</th><th>$/yr</th><th>Value index</th><th>Value</th></tr></thead>
    <tbody>{rows.map((r) => <tr key={`${r.player}-${r.team}`}><td>{r.player}</td><td>{r.team}</td><td>{r.pos_group}</td><td>{r.madden_ovr}</td><td>{r.grade}</td><td>${Number(r.apy).toFixed(1)}M</td><td>{r.value_index > 0 ? '+' : ''}{r.value_index}</td><td>{'★'.repeat(r.value)}{'☆'.repeat(5-r.value)}</td></tr>)}</tbody>
  </table></div></section>
}

export function ValueBoard() {
  const [position, setPosition] = useState('All')
  const state = useAsync(() => api.valueBoard(position), [position])
  return <div className="page">
    <section className="panel"><h2>💎 Value Board</h2>
      <p className="sub">Value index compares a player’s caliber percentile with his pay percentile at the same position. Positive values indicate more production caliber per dollar.</p>
      <Async state={state}>{(data) => <div className="controls"><div>
        <label className="field" htmlFor="value-position">Position</label>
        <select id="value-position" value={position} onChange={(e) => setPosition(e.target.value)}>
          {data.positions.map((pos) => <option key={pos}>{pos}</option>)}
        </select>
      </div></div>}</Async>
    </section>
    <Async state={state}>{(data) => <>
      <Board title={`Best values${position === 'All' ? '' : ` — ${position}`}`} rows={data.best} />
      <Board title="Biggest overpays" rows={data.worst} />
    </>}</Async>
  </div>
}
