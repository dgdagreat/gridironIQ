// ESPN-fantasy-style position color-coding: each position group gets a
// consistent accent so the data reads like a football app at a glance.
export const POS_COLOR = {
  QB: '#e24ba3',   // magenta
  RB: '#38b24a',   // green
  WR: '#1f9fe0',   // blue
  TE: '#f0820f',   // orange
  OL: '#8b909b', T: '#8b909b', G: '#8b909b', C: '#8b909b', // line — neutral
  IDL: '#a970d8',  // purple
  EDGE: '#e8562a', // red-orange
  LB: '#e0a52a',   // gold
  CB: '#2bc2c2',   // teal
  S: '#5f74e0',    // indigo
  SPEC: '#8b909b', // neutral
}

export function PosTag({ pos }) {
  const color = POS_COLOR[pos] || '#8b909b'
  return <span className="postag" style={{ color }}>{pos}</span>
}
