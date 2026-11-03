import { useMemo, useState } from 'react'
import { api } from '../api/client.js'
import { useAsync } from '../lib/useAsync.js'
import { Async } from '../components/Async.jsx'
import { Field } from '../components/Field.jsx'
import { num } from '../lib/format.js'

function GameTell({ season, gameId }) {
  const state = useAsync(() => api.filmSummary(season, gameId), [season, gameId])
  const [report, setReport] = useState({ loading: false, text: null, error: null })

  const write = async () => {
    setReport({ loading: true, text: null, error: null })
    try {
      const r = await api.filmBreakdown(season, gameId)
      setReport({ loading: false, text: r.report, error: null })
    } catch (e) {
      setReport({ loading: false, text: null, error: e })
    }
  }

  return (
    <div className="block card">
      <Async state={state} empty="No play-by-play for this game yet.">
        {(p) => {
          const lo = p.losing_offense
          return (
            <div>
              <div className="game-head">
                <h3>{p.tie ? `${p.away_team} tied ${p.home_team}` : `${p.winner} def. ${p.loser}`}</h3>
                {!p.tie && <span className="vs">the tape on why {p.loser} lost</span>}
              </div>
              {!p.tie && lo && (
                <div className="tiles">
                  <div className="tile"><div className="k">{p.loser} EPA/play</div><div className="v">{num(lo.epa_per_play)}</div></div>
                  <div className="tile"><div className="k">Pass EPA</div><div className="v">{num(lo.pass_epa)}</div></div>
                  <div className="tile"><div className="k">Sacks allowed</div><div className="v">{num(lo.sacks_allowed, 0)}</div></div>
                  <div className="tile"><div className="k">Turnovers</div><div className="v">{num(lo.turnovers, 0)}</div></div>
                </div>
              )}

              <div style={{ marginTop: 20, display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
                <button className="btn" onClick={write} disabled={report.loading}>
                  {report.loading ? 'Writing…' : 'Generate film report'}
                </button>
                <span className="hint">Model-written — the API needs ANTHROPIC_API_KEY.</span>
              </div>

              {report.error && <div className="state err" style={{ marginTop: 14 }}>⚠ {report.error.message}</div>}
              {report.text && <div className="report">{report.text}</div>}
            </div>
          )
        }}
      </Async>
    </div>
  )
}

export function FilmRoom({ meta }) {
  const seasons = useMemo(
    () => Array.from({ length: 4 }, (_, i) => meta.current_season - i),
    [meta.current_season],
  )
  const [season, setSeason] = useState(String(seasons[0]))
  const [week, setWeek] = useState('')
  const [gameId, setGameId] = useState('')
  const games = useAsync(() => api.filmGames(Number(season)), [season])

  const onSeason = (v) => { setSeason(v); setWeek(''); setGameId('') }

  return (
    <div className="wrap">
      <div className="lede">
        <div className="eyebrow">Film room</div>
        <h1>Every loss leaves a fingerprint.</h1>
        <p>
          Pick a completed game to see the box-score tell behind the result, then have the
          model write the full "why they lost" breakdown from the play-by-play.
        </p>
      </div>

      <div className="block card">
        <Async state={games} empty="No schedule for this season.">
          {(rows) => {
            const weeks = [...new Set(rows.map((r) => r.week))].sort((a, b) => a - b)
            const wk = week || String(weeks[0])
            const played = rows.filter((r) => r.week === Number(wk) && r.status === 'played')
            const gameOpts = [
              ['', played.length ? 'Select a game…' : 'No completed games this week'],
              ...played.map((g) => [g.game_id, `${g.away_team} @ ${g.home_team}  (${g.away_score}–${g.home_score})`]),
            ]
            return (
              <div className="controls">
                <Field label="Season" value={season} onChange={onSeason} options={seasons.map(String)} />
                <Field label="Week" value={wk} onChange={(v) => { setWeek(v); setGameId('') }}
                  options={weeks.map((w) => [String(w), `Week ${w}`])} />
                <Field label="Game" value={gameId} onChange={setGameId} options={gameOpts} width={260} />
              </div>
            )
          }}
        </Async>
      </div>

      {gameId && <GameTell season={Number(season)} gameId={gameId} />}
    </div>
  )
}
