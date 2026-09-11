import { useEffect, useState } from 'react';
import type { ReleaseNote } from '../types';
import { getReleases, submitReleaseEvent } from '../api/client';

interface Props {
  onAgentActivity: () => void;
}

export default function ReleasePanel({ onAgentActivity }: Props) {
  const [releases, setReleases] = useState<ReleaseNote[]>([]);
  const [text, setText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => getReleases().then(setReleases);

  useEffect(() => {
    load();
  }, []);

  const handleSubmit = async () => {
    if (!text.trim()) return;
    setSubmitting(true);
    setMessage(null);
    const result = await submitReleaseEvent(text);
    setText('');
    setSubmitting(false);
    setMessage(result.message);
    load();
    if (result.agent_actions.length > 0) onAgentActivity();
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5">
      <h3 className="font-semibold text-slate-900">Product Releases</h3>
      <p className="text-sm text-slate-500 mt-0.5 mb-3">
        Paste a release note. The agent looks for a rename ("X has been renamed to Y") and updates
        any tutorial that still uses the old term.
      </p>

      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder='e.g. "Meeting Summary has been renamed to Prepare."'
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <button
          onClick={handleSubmit}
          disabled={submitting || !text.trim()}
          className="px-4 py-2 rounded-lg bg-amber-500 text-white text-sm font-medium disabled:opacity-40 hover:bg-amber-600 transition-colors whitespace-nowrap"
        >
          {submitting ? 'Analyzing…' : 'Submit Release'}
        </button>
      </div>

      {message && (
        <div className="mt-3 text-sm bg-amber-50 text-amber-800 rounded-lg px-3 py-2">{message}</div>
      )}

      <div className="mt-4 space-y-1.5 max-h-40 overflow-y-auto">
        {releases.slice(0, 8).map((r) => (
          <div key={r.id} className="flex items-center gap-2 text-sm py-1.5 border-t border-slate-100 first:border-t-0">
            <span className="text-slate-400 font-mono text-xs">{r.id}</span>
            <span className="text-slate-700 truncate">{r.description}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
