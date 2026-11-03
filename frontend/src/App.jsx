import { useState } from 'react'
import { api } from './api/client.js'
import { useAsync } from './lib/useAsync.js'
import { Async } from './components/Async.jsx'
import { Boardroom } from './sections/Boardroom.jsx'
import { FilmRoom } from './sections/FilmRoom.jsx'
import { Maxer } from './sections/Maxer.jsx'
import { ValueBoard } from './sections/ValueBoard.jsx'

const SECTIONS = [
  { id: 'boardroom', label: 'Boardroom' },
  { id: 'filmroom', label: 'Film Room' },
  { id: 'maxer', label: 'SB Maxer' },
  { id: 'value', label: 'Value Board' },
]

const VIEWS = {
  boardroom: (m) => <Boardroom meta={m} />,
  filmroom: (m) => <FilmRoom meta={m} />,
  maxer: (m) => <Maxer meta={m} />,
  value: () => <ValueBoard />,
}

export default function App() {
  const [section, setSection] = useState('boardroom')
  const meta = useAsync(() => api.meta(), [])

  return (
    <>
      <header className="masthead">
        <div className="inner">
          <div className="wordmark">
            <span className="dot" />
            Gridiron<em>IQ</em>
          </div>
          <nav className="nav">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                className={section === s.id ? 'active' : ''}
                onClick={() => setSection(s.id)}
              >
                {s.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <Async state={meta}>
        {(m) => (VIEWS[section] ?? VIEWS.boardroom)(m)}
      </Async>
    </>
  )
}
