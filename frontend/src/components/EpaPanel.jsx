import { pct } from '../lib/format.js'

const sgn = (v, d = 3) =>
  v == null || Number.isNaN(v) ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(d)}`

// On-field efficiency from the PBP lakehouse (nflfastR EPA via the Spark
// medallion) — did the cap allocation translate to results? Only renders for
// seasons the lakehouse covers; ongoing/future seasons simply hide it.
export function EpaPanel({ epa, team, season }) {
  if (!epa) return null
  return (
    <div className="epa">
      <div className="list-title" style={{ marginTop: 28 }}>
        On-field efficiency · {team} {season} <span className="muted">— nflfastR EPA, PBP lakehouse</span>
      </div>
      <div className="tiles">
        <div className="tile"><div className="k">Off. EPA / play</div><div className="v">{sgn(epa.off_epa_play)}</div></div>
        <div className="tile"><div className="k">Def. EPA / play allowed</div><div className="v">{sgn(epa.def_epa_play_allowed)}</div></div>
        <div className="tile">
          <div className="k">Net EPA / play</div>
          <div className="v">{sgn(epa.net_epa_play)}<small> · #{epa.net_epa_rank} of {epa.n_teams}</small></div>
        </div>
        <div className="tile"><div className="k">Off. success rate</div><div className="v">{pct(epa.off_success_rate, 0)}</div></div>
        <div className="tile"><div className="k">Off. explosive rate</div><div className="v">{pct(epa.off_explosive_rate, 0)}</div></div>
        <div className="tile"><div className="k">Def. pressure rate</div><div className="v">{pct(epa.def_pressure_rate, 0)}</div></div>
      </div>
    </div>
  )
}
