import { useEffect, useMemo, useState } from 'react';
import type { Tutorial } from '../../types';
import { getTutorials } from '../../api/client';
import TutorialCard from '../../components/TutorialCard';

export default function TutorialHubPage() {
  const [tutorials, setTutorials] = useState<Tutorial[] | null>(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    getTutorials().then(setTutorials);
  }, []);

  const filtered = useMemo(() => {
    if (!tutorials) return [];
    const q = query.trim().toLowerCase();
    if (!q) return tutorials;
    return tutorials.filter(
      (t) => t.title.toLowerCase().includes(q) || t.description.toLowerCase().includes(q),
    );
  }, [tutorials, query]);

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Tutorial Hub</h1>
        <p className="text-slate-500 mt-1">Search and browse Copilot training tutorials.</p>
      </div>

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search tutorials…"
        className="w-full max-w-md rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400 mb-6"
      />

      {tutorials === null ? (
        <p className="text-slate-400 text-sm">Loading tutorials…</p>
      ) : filtered.length === 0 ? (
        <p className="text-slate-400 text-sm">No tutorials match "{query}".</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((t) => (
            <TutorialCard key={t.id} tutorial={t} />
          ))}
        </div>
      )}
    </div>
  );
}
