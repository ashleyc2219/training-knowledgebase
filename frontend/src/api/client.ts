// Mock implementation of the backend API described in the design doc (§29).
// Every function signature/shape mirrors the real REST endpoint it stands in
// for, and each resolves a Promise (like a real fetch would) so swapping in
// `fetch(...)` later touches only this file, not the components that call it.

import {
  tutorials,
  tutorialVersions,
  feedback as feedbackSeed,
  knowledgeGaps,
  agentActions,
} from './mockData';
import type {
  Tutorial,
  TutorialVersion,
  Feedback,
  KnowledgeGap,
  AgentAction,
  TutorialHealth,
  VersionDiff,
} from '../types';

const LATENCY = 150;
const delay = <T>(value: T): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), LATENCY));

// In-memory mutable copy so submitted feedback shows up without a reload.
let feedbackStore: Feedback[] = [...feedbackSeed];

// ---- Tutorials --------------------------------------------------------

export async function getTutorials(): Promise<Tutorial[]> {
  return delay([...tutorials]);
}

export async function getTutorial(id: string): Promise<Tutorial | undefined> {
  return delay(tutorials.find((t) => t.id === id || t.slug === id));
}

export async function getTutorialVersions(tutorialId: string): Promise<TutorialVersion[]> {
  return delay(
    tutorialVersions
      .filter((v) => v.tutorial_id === tutorialId)
      .sort((a, b) => a.version - b.version),
  );
}

export async function getTutorialVersion(versionId: string): Promise<TutorialVersion | undefined> {
  return delay(tutorialVersions.find((v) => v.id === versionId));
}

function diffContent(fromContent: string, toContent: string) {
  const fromLines = fromContent.split('\n');
  const toLines = toContent.split('\n');
  const lines: VersionDiff['diff_lines'] = [];
  const max = Math.max(fromLines.length, toLines.length);
  for (let i = 0; i < max; i++) {
    const a = fromLines[i];
    const b = toLines[i];
    if (a === b) {
      if (a !== undefined) lines.push({ type: 'context', text: a });
    } else {
      if (a !== undefined) lines.push({ type: 'removed', text: a });
      if (b !== undefined) lines.push({ type: 'added', text: b });
    }
  }
  return lines;
}

export async function getTutorialDiff(
  tutorialId: string,
  fromVersion: number,
  toVersion: number,
): Promise<VersionDiff | undefined> {
  const versions = tutorialVersions.filter((v) => v.tutorial_id === tutorialId);
  const from = versions.find((v) => v.version === fromVersion);
  const to = versions.find((v) => v.version === toVersion);
  if (!from || !to) return delay(undefined);
  return delay({
    tutorial_id: tutorialId,
    from_version: fromVersion,
    to_version: toVersion,
    diff_lines: diffContent(from.content, to.content),
    reason: to.change_reason,
    evidence: to.evidence,
    agent_action: `${to.change_type}_TUTORIAL`,
    outcome: to.outcome ?? 'No outcome recorded yet.',
  });
}

// ---- Feedback -----------------------------------------------------------

export async function getFeedback(tutorialId: string): Promise<Feedback[]> {
  return delay(
    feedbackStore
      .filter((f) => f.tutorial_id === tutorialId)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
  );
}

export async function submitFeedback(
  tutorialId: string,
  tutorialVersionId: string,
  rating: number,
  comment: string,
): Promise<Feedback> {
  const entry: Feedback = {
    id: `fb_${Date.now()}`,
    tutorial_id: tutorialId,
    tutorial_version_id: tutorialVersionId,
    user_id: 'you',
    rating,
    comment,
    created_at: new Date().toISOString(),
  };
  feedbackStore = [entry, ...feedbackStore];
  return delay(entry);
}

// ---- Knowledge gaps -------------------------------------------------------

export async function getKnowledgeGaps(): Promise<KnowledgeGap[]> {
  return delay([...knowledgeGaps]);
}

export async function getKnowledgeGap(id: string): Promise<KnowledgeGap | undefined> {
  return delay(knowledgeGaps.find((g) => g.id === id));
}

// ---- Agent actions -------------------------------------------------------

export async function getAgentActions(): Promise<AgentAction[]> {
  return delay(
    [...agentActions].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
  );
}

export async function getAgentAction(id: string): Promise<AgentAction | undefined> {
  return delay(agentActions.find((a) => a.id === id));
}

// ---- Analytics / tutorial health ------------------------------------------

export async function getTutorialHealth(): Promise<TutorialHealth[]> {
  const results: TutorialHealth[] = tutorials.map((t) => {
    const versions = tutorialVersions
      .filter((v) => v.tutorial_id === t.id)
      .sort((a, b) => a.version - b.version);

    const history = versions.map((v) => {
      const fb = feedbackStore.filter((f) => f.tutorial_version_id === v.id);
      const avg = fb.length ? fb.reduce((s, f) => s + f.rating, 0) / fb.length : t.average_rating;
      const negative = fb.filter((f) => f.rating <= 2).length;
      return {
        version: v.version,
        average_rating: Math.round(avg * 10) / 10,
        negative_feedback_count: negative,
        related_ticket_count: v.change_type === 'CREATE' ? v.evidence.length : 0,
        outdated_steps: v.change_type === 'UPDATE' ? 0 : 0,
      };
    });

    const latest = history[history.length - 1];
    const relatedTickets = knowledgeGaps
      .filter((g) => g.feature_id === t.feature_id)
      .reduce((s, g) => s + g.evidence_count, 0);

    const needsAttention = t.status === 'needs_review' || (latest?.average_rating ?? 5) < 3.2;

    return {
      tutorial_id: t.id,
      tutorial_title: t.title,
      status: t.status,
      current_rating: latest?.average_rating ?? t.average_rating,
      related_tickets: relatedTickets,
      negative_feedback: latest?.negative_feedback_count ?? 0,
      ai_analysis: needsAttention
        ? `${t.title} is trending below target rating. Recent feedback and related tickets suggest a section may need clarification.`
        : `${t.title} is performing well. No action recommended.`,
      recommended_action: needsAttention ? 'REFINE' : 'NO_ACTION',
      history,
    };
  });
  return delay(results);
}

export interface AnalyticsOverview {
  total_tutorials: number;
  active_knowledge_gaps: number;
  agent_actions_last_30_days: number;
  average_rating_across_tutorials: number;
}

export async function getAnalyticsOverview(): Promise<AnalyticsOverview> {
  const avg =
    tutorials.reduce((s, t) => s + t.average_rating, 0) / (tutorials.length || 1);
  return delay({
    total_tutorials: tutorials.length,
    active_knowledge_gaps: knowledgeGaps.filter((g) => g.status !== 'resolved' && g.status !== 'ignored').length,
    agent_actions_last_30_days: agentActions.length,
    average_rating_across_tutorials: Math.round(avg * 10) / 10,
  });
}
