const POS_FULL = {
  QB: 'Quarterback', RB: 'Running Back', WR: 'Wide Receiver', TE: 'Tight End',
  T: 'Offensive Tackle', G: 'Offensive Guard', C: 'Center',
  OL: 'Offensive Line', IDL: 'Interior D-Line', EDGE: 'Edge Rusher',
  LB: 'Linebacker', CB: 'Cornerback', S: 'Safety', SPEC: 'Special Teams',
}

function verdictBadge(v) {
  if (v.startsWith('underpaid')) return <span className="badge up">worth paying up</span>
  if (v.startsWith('overpaid')) return <span className="badge value">overpaid leaguewide</span>
  return <span className="badge fair">fairly paid</span>
}

export function EfficiencyVerdictTable({ data }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Position</th>
          <th className="num">Champ premium</th>
          <th className="num">Spend↔win corr</th>
          <th>Verdict</th>
        </tr>
      </thead>
      <tbody>
        {data.map((r) => (
          <tr key={r.pos_group}>
            <td>{POS_FULL[r.pos_group] ?? r.pos_group}</td>
            <td className="num">{(r.champion_premium * 100).toFixed(2)}%</td>
            <td className="num">{r.corr_win?.toFixed(3) ?? '—'}</td>
            <td>{verdictBadge(r.verdict)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
