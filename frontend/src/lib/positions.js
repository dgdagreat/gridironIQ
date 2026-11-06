// Shared position metadata for the Boardroom visuals (position full names, the
// offense/defense/special-teams unit split, unit colors, and the fixed spoke
// order used by the blueprint radar). Kept in one place so every chart reads the
// cap the same way.

export const POS_FULL = {
  QB: 'Quarterback', RB: 'Running Back', WR: 'Wide Receiver', TE: 'Tight End',
  OL: 'Offensive Line', T: 'Offensive Tackle', G: 'Offensive Guard', C: 'Center',
  IDL: 'Interior D-Line', EDGE: 'Edge Rusher', LB: 'Linebacker',
  CB: 'Cornerback', S: 'Safety', SPEC: 'Special Teams',
}

export const POS_UNIT = {
  QB: 'Offense', RB: 'Offense', WR: 'Offense', TE: 'Offense', T: 'Offense',
  G: 'Offense', C: 'Offense', OL: 'Offense',
  IDL: 'Defense', EDGE: 'Defense', LB: 'Defense', CB: 'Defense', S: 'Defense',
  SPEC: 'Special teams',
}

export const UNITS = ['Offense', 'Defense', 'Special teams']

export const UNIT_COLOR = {
  Offense: 'var(--pay)',
  Defense: 'var(--accent)',
  'Special teams': 'var(--value)',
}

// Fixed spoke order (offense arc, then defense, then specialists) so the radar
// shape is comparable across teams and seasons.
export const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'T', 'G', 'C', 'OL', 'IDL', 'EDGE', 'LB', 'CB', 'S', 'SPEC']

// The season every Boardroom view opens on: the current/default season when it's
// available, otherwise the newest season at or before it (never a far-future
// projection). Keeps the app anchored on 2026 and rolls forward on its own.
export function defaultSeason(meta) {
  if (meta.seasons.includes(meta.current_season)) return meta.current_season
  const atOrBelow = meta.seasons.filter((s) => s <= meta.current_season)
  return atOrBelow.length ? Math.max(...atOrBelow) : meta.seasons[0]
}
