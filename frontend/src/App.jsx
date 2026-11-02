import { useState } from 'react'
import { api } from './api/client.js'
import { useAsync } from './lib/useAsync.js'
import { Async } from './components/Async.jsx'
import { Boardroom } from './tabs/Boardroom.jsx'
import { FilmRoom } from './tabs/FilmRoom.jsx'
import { Maxer } from './tabs/Maxer.jsx'
import { ValueBoard } from './tabs/ValueBoard.jsx'

const TABS = [
  { id: 'boardroom', label: 'Boardroom' },
  { id: 'filmroom', label: 'Film Room' },
  { id: 'maxer', label: 'Super Bowl Maxer' },
  { id: 'valueboard', label: 'Value Board' },
]

export default function App() {
  const [tab, setTab] = useState('boardroom')
  const meta = useAsync(() => api.meta(), [])

  return (
    <>
      <header className="app-header">
        <div className="inner">
          <h1>🏈 GridironIQ</h1>
          <p>Cap efficiency &amp; film breakdowns — the React frontend over the gridiron analytics.</p>
          <nav className="tabbar">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={tab === t.id ? 'active' : ''}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main>
        <Async state={meta}>
          {(m) => (
            tab === 'boardroom' ? <Boardroom meta={m} />
              : tab === 'filmroom' ? <FilmRoom meta={m} />
                : tab === 'maxer' ? <Maxer meta={m} /> : <ValueBoard />
          )}
        </Async>
      </main>
    </>
  )
}
