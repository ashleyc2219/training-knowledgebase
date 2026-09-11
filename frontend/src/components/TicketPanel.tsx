import { useEffect, useState } from 'react';
import type { Ticket } from '../types';
import { getTickets, submitTicketEvent } from '../api/client';

const EXAMPLES = [
  'How do I prepare for a meeting?',
  'Where is Meeting Summary?',
  'How can Copilot help with customer meetings?',
];

interface Props {
  onAgentActivity: () => void;
}

export default function TicketPanel({ onAgentActivity }: Props) {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [text, setText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = () => getTickets().then(setTickets);

  useEffect(() => {
    load();
  }, []);

  const handleSubmit = async () => {
    if (!text.trim()) return;
    setSubmitting(true);
    setMessage(null);
    const result = await submitTicketEvent(text);
    setText('');
    setSubmitting(false);
    setMessage(result.message);
    load();
    if (result.agent_actions.length > 0) onAgentActivity();
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5">
      <h3 className="font-semibold text-slate-900">Incoming Tickets</h3>
      <p className="text-sm text-slate-500 mt-0.5 mb-3">
        Simulate a new support ticket arriving. The agent searches existing knowledge and either
        matches it, grows a candidate knowledge gap, or promotes one to a tutorial at 3 related tickets.
      </p>

      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder={`e.g. "${EXAMPLES[tickets.length % EXAMPLES.length]}"`}
          className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
        />
        <button
          onClick={handleSubmit}
          disabled={submitting || !text.trim()}
          className="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium disabled:opacity-40 hover:bg-indigo-700 transition-colors whitespace-nowrap"
        >
          {submitting ? 'Analyzing…' : 'Submit Ticket'}
        </button>
      </div>

      {message && (
        <div className="mt-3 text-sm bg-indigo-50 text-indigo-800 rounded-lg px-3 py-2">{message}</div>
      )}

      <div className="mt-4 space-y-1.5 max-h-56 overflow-y-auto">
        {tickets.slice(0, 12).map((t) => (
          <div key={t.id} className="flex items-center justify-between gap-3 text-sm py-1.5 border-t border-slate-100 first:border-t-0">
            <div className="min-w-0">
              <span className="text-slate-400 font-mono text-xs mr-2">{t.id}</span>
              <span className="text-slate-700">{t.title}</span>
            </div>
            {t.matched_gap_topic ? (
              <span className="shrink-0 text-[11px] px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">
                {t.matched_gap_topic}
              </span>
            ) : (
              <span className="shrink-0 text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
                Unmatched
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
