import type { ReactNode } from 'react';
import { Routes, Route, Navigate, NavLink } from 'react-router-dom';
import TutorialHubPage from './pages/tutorials/TutorialHubPage';
import TutorialDetailPage from './pages/tutorials/TutorialDetailPage';
import ImprovementConsolePage from './pages/improvement/ImprovementConsolePage';

function NavTab({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-3 py-2 text-sm font-medium rounded-md transition-colors ${
          isActive
            ? 'bg-indigo-600 text-white'
            : 'text-slate-600 hover:bg-slate-200/70 hover:text-slate-900'
        }`
      }
    >
      {children}
    </NavLink>
  );
}

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-200 bg-white sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="h-6 w-6 rounded-md bg-indigo-600 flex items-center justify-center text-white text-xs font-bold">
              K
            </div>
            <span className="font-semibold text-slate-900">Training Knowledge Base</span>
          </div>
          <nav className="flex items-center gap-1">
            <NavTab to="/tutorials">Tutorial Hub</NavTab>
            <NavTab to="/improvement">AI Improvement Console</NavTab>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/tutorials" replace />} />
          <Route path="/tutorials" element={<TutorialHubPage />} />
          <Route path="/tutorials/:slug" element={<TutorialDetailPage />} />
          <Route path="/improvement" element={<ImprovementConsolePage />} />
        </Routes>
      </main>
    </div>
  );
}
