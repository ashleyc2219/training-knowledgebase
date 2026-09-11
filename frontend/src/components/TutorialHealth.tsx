import { Link } from 'react-router-dom';
import type { TutorialHealth as TutorialHealthType } from '../types';
import StatusBadge from './StatusBadge';

interface Props {
  health: TutorialHealthType;
  slug: string;
  onViewHistory: () => void;
  expanded: boolean;
}

export default function TutorialHealth({ health, slug, onViewHistory, expanded }: Props) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5">
      <div className="flex items-start justify-between gap-3">
        <h4 className="font-semibold text-slate-900">{health.tutorial_title}</h4>
        <StatusBadge status={health.status} />
      </div>

      <div className="grid grid-cols-3 gap-4 mt-4">
        <div>
          <div className="text-xs text-slate-500">Current Rating</div>
          <div className="text-lg font-semibold text-slate-900">{health.current_rating.toFixed(1)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Related Tickets</div>
          <div className="text-lg font-semibold text-slate-900">{health.related_tickets}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500">Negative Feedback</div>
          <div className="text-lg font-semibold text-slate-900">{health.negative_feedback}</div>
        </div>
      </div>

      <div className="mt-4 bg-slate-50 rounded-lg p-3">
        <div className="text-xs font-medium text-slate-500 mb-1">AI Analysis</div>
        <p className="text-sm text-slate-700">{health.ai_analysis}</p>
      </div>

      <div className="flex items-center justify-between mt-4">
        <div className="text-sm">
          <span className="text-slate-500">Recommended Action: </span>
          <span
            className={`font-semibold ${
              health.recommended_action === 'NO_ACTION' ? 'text-slate-500' : 'text-indigo-600'
            }`}
          >
            {health.recommended_action}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to={`/tutorials/${slug}`}
            className="text-sm font-medium text-slate-600 hover:text-slate-900 px-3 py-1.5 rounded-lg hover:bg-slate-100"
          >
            View Tutorial
          </Link>
          <button
            onClick={onViewHistory}
            className="text-sm font-medium text-indigo-600 hover:text-indigo-800 px-3 py-1.5 rounded-lg hover:bg-indigo-50"
          >
            {expanded ? 'Hide Version History' : 'View Version History'}
          </button>
        </div>
      </div>
    </div>
  );
}
