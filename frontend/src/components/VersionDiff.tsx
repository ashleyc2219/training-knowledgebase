import { useEffect, useState } from 'react';
import type { TutorialVersion, VersionDiff as VersionDiffType } from '../types';
import { getTutorialDiff } from '../api/client';

const SOURCE_LABEL: Record<string, string> = {
  CREATE: 'Initial Tutorial',
  REFINE: 'User Feedback',
  UPDATE: 'Product Release',
  RETIRE: 'Retired',
};

interface Props {
  tutorialId: string;
  versions: TutorialVersion[]; // ascending order
}

export default function VersionDiff({ tutorialId, versions }: Props) {
  const sorted = [...versions].sort((a, b) => b.version - a.version); // newest first
  const [selected, setSelected] = useState<number>(sorted[0]?.version ?? 1);
  const [diff, setDiff] = useState<VersionDiffType | null>(null);
  const [loading, setLoading] = useState(false);

  const selectedVersion = versions.find((v) => v.version === selected);
  const isInitial = selected === Math.min(...versions.map((v) => v.version));

  useEffect(() => {
    if (isInitial) {
      setDiff(null);
      return;
    }
    setLoading(true);
    getTutorialDiff(tutorialId, selected - 1, selected)
      .then((d) => setDiff(d ?? null))
      .finally(() => setLoading(false));
  }, [tutorialId, selected, isInitial]);

  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-slate-200 bg-slate-50">
        <h4 className="text-sm font-semibold text-slate-900">Version History</h4>
      </div>

      <div className="flex flex-col sm:flex-row">
        <div className="sm:w-56 shrink-0 border-b sm:border-b-0 sm:border-r border-slate-200 p-2">
          {sorted.map((v) => (
            <button
              key={v.id}
              onClick={() => setSelected(v.version)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                selected === v.version
                  ? 'bg-indigo-50 text-indigo-700 font-medium'
                  : 'text-slate-600 hover:bg-slate-50'
              }`}
            >
              <div>v{v.version}</div>
              <div className="text-xs text-slate-400">← {SOURCE_LABEL[v.change_type] ?? v.change_type}</div>
            </button>
          ))}
        </div>

        <div className="flex-1 p-5">
          {isInitial ? (
            <div className="text-sm text-slate-600">
              <p className="font-medium text-slate-900 mb-1">v{selected} — Initial Tutorial</p>
              <p>{selectedVersion?.change_reason}</p>
              <div className="flex flex-wrap gap-1.5 mt-3">
                {selectedVersion?.evidence.map((e, i) => (
                  <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                    {e}
                  </span>
                ))}
              </div>
            </div>
          ) : loading ? (
            <p className="text-sm text-slate-400">Loading diff…</p>
          ) : diff ? (
            <div className="space-y-4">
              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">
                  v{diff.from_version} → v{diff.to_version}
                </p>
                <div className="font-mono text-xs bg-slate-900 rounded-lg p-3 space-y-0.5 overflow-x-auto">
                  {diff.diff_lines
                    .filter((l) => l.type !== 'context' || l.text.trim() !== '')
                    .map((line, i) => (
                      <div
                        key={i}
                        className={
                          line.type === 'added'
                            ? 'text-emerald-400'
                            : line.type === 'removed'
                            ? 'text-rose-400'
                            : 'text-slate-500'
                        }
                      >
                        {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}
                        {line.text || ' '}
                      </div>
                    ))}
                </div>
              </div>

              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Reason</p>
                <p className="text-sm text-slate-700">{diff.reason}</p>
              </div>

              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Evidence</p>
                <div className="flex flex-wrap gap-1.5">
                  {diff.evidence.map((e, i) => (
                    <span key={i} className="text-[11px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                      {e}
                    </span>
                  ))}
                </div>
              </div>

              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Agent Action</p>
                <p className="text-sm text-slate-700">{diff.agent_action}</p>
              </div>

              <div>
                <p className="text-xs font-medium text-slate-500 mb-1">Outcome</p>
                <p className="text-sm text-emerald-700">{diff.outcome}</p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-400">No diff available.</p>
          )}
        </div>
      </div>
    </div>
  );
}
