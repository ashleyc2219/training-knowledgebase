import type { KnowledgeGap as KnowledgeGapType } from '../types';
import StatusBadge from './StatusBadge';

export default function KnowledgeGap({ gap }: { gap: KnowledgeGapType }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5">
      <div className="flex items-start justify-between gap-3">
        <h4 className="font-medium text-slate-900">{gap.topic}</h4>
        <StatusBadge status={gap.status} />
      </div>
      <p className="text-sm text-slate-600 mt-1">{gap.description}</p>
      <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
        <span>{gap.evidence_count} source ticket{gap.evidence_count === 1 ? '' : 's'}</span>
        <span>Last seen {new Date(gap.last_detected_at).toLocaleDateString()}</span>
      </div>
      {gap.source_tickets.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {gap.source_tickets.map((t) => (
            <span key={t} className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
