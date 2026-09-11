import { useEffect, useState } from 'react';
import type { AgentAction, KnowledgeGap as KnowledgeGapType, Tutorial, TutorialHealth as TutorialHealthType, TutorialVersion } from '../../types';
import {
  getAgentActions,
  getKnowledgeGaps,
  getTutorialHealth,
  getTutorials,
  getTutorialVersions,
} from '../../api/client';
import KnowledgeGap from '../../components/KnowledgeGap';
import TutorialHealth from '../../components/TutorialHealth';
import AgentActivity from '../../components/AgentActivity';
import VersionDiff from '../../components/VersionDiff';

export default function ImprovementConsolePage() {
  const [gaps, setGaps] = useState<KnowledgeGapType[] | null>(null);
  const [health, setHealth] = useState<TutorialHealthType[] | null>(null);
  const [actions, setActions] = useState<AgentAction[] | null>(null);
  const [tutorials, setTutorials] = useState<Tutorial[]>([]);
  const [expandedTutorialId, setExpandedTutorialId] = useState<string | null>(null);
  const [versionsByTutorial, setVersionsByTutorial] = useState<Record<string, TutorialVersion[]>>({});

  useEffect(() => {
    getKnowledgeGaps().then(setGaps);
    getTutorialHealth().then(setHealth);
    getAgentActions().then(setActions);
    getTutorials().then(setTutorials);
  }, []);

  const toggleHistory = async (tutorialId: string) => {
    if (expandedTutorialId === tutorialId) {
      setExpandedTutorialId(null);
      return;
    }
    if (!versionsByTutorial[tutorialId]) {
      const vs = await getTutorialVersions(tutorialId);
      setVersionsByTutorial((prev) => ({ ...prev, [tutorialId]: vs }));
    }
    setExpandedTutorialId(tutorialId);
  };

  const slugFor = (tutorialId: string) => tutorials.find((t) => t.id === tutorialId)?.slug ?? '';

  return (
    <div className="max-w-6xl mx-auto px-6 py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-slate-900">AI Improvement Console</h1>
        <p className="text-slate-500 mt-1">
          What the agent discovered, what it changed, and why — every action backed by evidence.
        </p>
      </div>

      <section className="mb-10">
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-3">Knowledge Gaps</h2>
        {gaps === null ? (
          <p className="text-slate-400 text-sm">Loading…</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {gaps.map((g) => (
              <KnowledgeGap key={g.id} gap={g} />
            ))}
          </div>
        )}
      </section>

      <section className="mb-10">
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-3">Tutorial Health</h2>
        {health === null ? (
          <p className="text-slate-400 text-sm">Loading…</p>
        ) : (
          <div className="space-y-4">
            {health.map((h) => (
              <div key={h.tutorial_id}>
                <TutorialHealth
                  health={h}
                  slug={slugFor(h.tutorial_id)}
                  expanded={expandedTutorialId === h.tutorial_id}
                  onViewHistory={() => toggleHistory(h.tutorial_id)}
                />
                {expandedTutorialId === h.tutorial_id && versionsByTutorial[h.tutorial_id] && (
                  <div className="mt-3">
                    <VersionDiff tutorialId={h.tutorial_id} versions={versionsByTutorial[h.tutorial_id]} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wide mb-3">Recent Agent Actions</h2>
        {actions === null ? (
          <p className="text-slate-400 text-sm">Loading…</p>
        ) : (
          <div className="bg-white border border-slate-200 rounded-xl p-5">
            <AgentActivity actions={actions} />
          </div>
        )}
      </section>
    </div>
  );
}
