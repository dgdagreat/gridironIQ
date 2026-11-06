// Thin fetch wrapper around the GridironIQ JSON API (gridiron/api.py).
// In dev, Vite proxies /api -> the FastAPI server, so the base stays relative.
const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* non-JSON error body */
    }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  meta: () => request('/api/meta'),
  championPremium: () => request('/api/champion-premium'),
  efficiencyVerdict: () => request('/api/efficiency-verdict'),
  teamSeason: (team, season) => request(`/api/team-season/${team}/${season}`),
  archetypes: (k = 5) => request(`/api/archetypes?k=${k}`),
  maxer: (team) => request(`/api/maxer/${encodeURIComponent(team)}`),
  maxerSimulate: (team, signed, traded) =>
    request(`/api/maxer/${encodeURIComponent(team)}/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ signed, traded }),
    }),
  valueBoard: (position = 'All', limit = 25) =>
    request(`/api/value-board?position=${encodeURIComponent(position)}&limit=${limit}`),
  compare: (season, teams) =>
    request(`/api/compare?season=${season}&teams=${encodeURIComponent(teams.join(','))}`),
  filmGames: (season) => request(`/api/film/games?season=${season}`),
  filmSummary: (season, gameId) =>
    request(`/api/film/summary?season=${season}&game_id=${encodeURIComponent(gameId)}`),
  filmSubtotals: (season, gameId) =>
    request(`/api/film/subtotals?season=${season}&game_id=${encodeURIComponent(gameId)}`),
  filmPlays: (season, gameId) =>
    request(`/api/film/plays?season=${season}&game_id=${encodeURIComponent(gameId)}`),
  filmBreakdown: (season, gameId) =>
    request('/api/film/breakdown', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ season, game_id: gameId }),
    }),
}
