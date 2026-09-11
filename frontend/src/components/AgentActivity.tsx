import type { AgentAction } from '../types';

const ACTION_LABELS: Record<string, string> = {
  CREATE_KNOWLEDGE_GAP: 'Detected Knowledge Gap',
  CREATE_TUTORIAL: 'Created Tutorial',
  REFINE_TUTORIAL: 'Refined Tutorial',
  UPDATE_TUTORIAL: 'Updated Tutorial',
  RETIRE_TUTORIAL: 'Retired Tutorial',
};

const ACTION_DOTS: Record<string, string> = {
  CREATE_KNOWLEDGE_GAP: 'bg-slate-400',
  CREATE_TUTORIAL: 'bg-emerald-500',
  REFINE_TUTORIAL: 'bg-indigo-500',
  UPDATE_TUTORIAL: 'bg-amber-500',
  RETIRE_TUTORIAL: 'bg-rose-500',
};

export default function AgentActivity({ actions }: { actions: AgentAction[] }) {
  return (
    <ol className="relative border-l border-slate-200 pl-5 space-y-6">
      {actions.map((action) => (
        <li key={action.id} className="relative">
          <span
            className={`absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-slate-50 ${
              ACTION_DOTS[action.action_type] ?? 'bg-slate-400'
            }`}
          />
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-sm font-medium text-slate-900">
              {ACTION_LABELS[action.action_type] ?? action.action_type}
            </span>
            <span className="text-xs text-slate-400 whitespace-nowrap">
              {new Date(action.created_at).toLocaleString(undefined, {
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
              })}
            </span>
          </div>
          <div className="text-sm text-slate-700 mt-0.5">{action.target_title}</div>
          <p className="text-sm text-slate-500 mt-1">{action.reason}</p>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {action.evidence.map((e, i) => (
              <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                {e}
              </span>
            ))}
          </div>
          {action.outcome && (
            <p className="text-sm text-emerald-700 mt-2">→ {action.outcome}</p>
          )}
        </li>
      ))}
    </ol>
  );
}
