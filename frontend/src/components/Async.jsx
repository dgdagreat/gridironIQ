// Render helper: shows loading / error / empty states around async data.
export function Async({ state, children, empty = 'Nothing to show.' }) {
  if (state.loading) {
    return <div className="state"><span className="spinner" /> Loading…</div>
  }
  if (state.error) {
    return <div className="state err">⚠ {state.error.message}</div>
  }
  const d = state.data
  if (d == null || (Array.isArray(d) && d.length === 0)) {
    return <div className="state">{empty}</div>
  }
  return children(d)
}
