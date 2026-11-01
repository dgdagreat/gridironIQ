import { useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'

const num = (x, d = 2) => (x == null || Number.isNaN(x) ? '—' : Number(x).toFixed(d))

function GameSummary({ season, gameId }) {
  const state = useAsync(() => api.filmSummary(season, gameId), [season, gameId])
  const [report, setReport] = useState({ loading: false, text: null, error: null })

  const writeReport = async () => {
    setReport({ loading: true, text: null, error: null })
    try {
      const r = await api.filmBreakdown(season, gameId)
      setReport({ loading: false, text: r.report, error: null })
    } catch (e) {
      setReport({ loading: false, text: null, error: e })
    }
  }

  return (
    <Async state={state} empty="No play-by-play for this game yet.">
      {(p) => {
        const lo = p.losing_offense
        return (
          <div>
            <h2 style={{ marginTop: 0 }}>
              {p.tie ? `${p.away_team ?? ''} tied ${p.home_team ?? ''}` : `${p.winner} def. ${p.loser}`}
            </h2>
            {!p.tie && lo && (
              <div className="stat-grid" style={{ marginBottom: 18 }}>
                <div className="stat"><div className="label">{p.loser} EPA/play</div><div className="value">{num(lo.epa_per_play)}</div></div>
                <div className="stat"><div className="label">Pass EPA</div><div className="value">{num(lo.pass_epa)}</div></div>
                <div className="stat"><div className="label">Sacks allowed</div><div className="value">{num(lo.sacks_allowed, 0)}</div></div>
                <div className="stat"><div className="label">Turnovers</div><div className="value">{num(lo.turnovers, 0)}</div></div>
              </div>
            )}

            <button className="primary" onClick={writeReport} disabled={report.loading}>
              {report.loading ? 'Writing the report…' : '✍ Write the film report'}
            </button>
            <span className="muted" style={{ marginLeft: 12 }}>Uses Anthropic — needs ANTHROPIC_API_KEY on the API.</span>

            {report.error && <div className="state error" style={{ marginTop: 14 }}>⚠ {report.error.message}</div>}
            {report.text && <div className="report" style={{ marginTop: 16 }}>{report.text}</div>}
          </div>
        )
      }}
    </Async>
  )
}

export function FilmRoom({ meta }) {
  const seasons = useMemo(
    () => Array.from({ length: 4 }, (_, i) => meta.current_season - i),
    [meta.current_season],
  )
  const [season, setSeason] = useState(seasons[0])
  const games = useAsync(() => api.filmGames(season), [season])

  const [week, setWeek] = useState(null)
  const [loaded, setLoaded] = useState(null) // game_id to show

  return (
    <div className="page">
      <div className="panel">
        <h2 style={{ marginTop: 0 }}>Film Room</h2>
        <p className="sub">
          Pick a completed game to see its box-score tell, then have the model write the "why they lost" breakdown.
          Play-by-play (~40&nbsp;MB/season) loads on the API's first hit for a season.
        </p>

        <div className="controls">
          <div>
            <label className="field">Season</label>
            <select value={season} onChange={(e) => { setSeason(Number(e.target.value)); setWeek(null); setLoaded(null) }}>
              {seasons.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <Async state={games} empty="No schedule for this season.">
            {(rows) => {
              const weeks = [...new Set(rows.map((r) => r.week))].sort((a, b) => a - b)
              const wk = week ?? weeks[0]
              const wkGames = rows.filter((r) => r.week === wk)
              return (
                <>
                  <div>
                    <label className="field">Week</label>
                    <select value={wk} onChange={(e) => { setWeek(Number(e.target.value)); setLoaded(null) }}>
                      {weeks.map((w) => <option key={w} value={w}>Week {w}</option>)}
                    </select>
                  </div>
                  <div style={{ flex: '2 1 280px' }}>
                    <label className="field">Game</label>
                    <select
                      defaultValue=""
                      onChange={(e) => setLoaded(e.target.value || null)}
                    >
                      <option value="">Select a game…</option>
                      {wkGames.map((g) => (
                        <option key={g.game_id} value={g.status === 'played' ? g.game_id : ''} disabled={g.status !== 'played'}>
                          {g.away_team} @ {g.home_team}
                          {g.status === 'played'
                            ? `  (${g.away_score}–${g.home_score})`
                            : '  · scheduled'}
                        </option>
                      ))}
                    </select>
                  </div>
                </>
              )
            }}
          </Async>
        </div>
      </div>

      {loaded && (
        <div className="panel">
          <GameSummary season={season} gameId={loaded} />
        </div>
      )}
    </div>
  )
}
