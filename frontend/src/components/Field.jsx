// Labelled, custom-styled <select>.
export function Field({ label, value, onChange, options, width }) {
  return (
    <label className="field" style={width ? { flex: `1 1 ${width}px`, minWidth: width } : undefined}>
      <span>{label}</span>
      <div className="select">
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {options.map((o) => {
            const [val, text] = Array.isArray(o) ? o : [o, o]
            return <option key={val} value={val}>{text}</option>
          })}
        </select>
      </div>
    </label>
  )
}
