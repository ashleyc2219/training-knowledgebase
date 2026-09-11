// A small simulated "Training Agent" that runs entirely in the browser.
// It exists so the frontend can demo the real product loop — ticket in,
// knowledge gap detected, tutorial generated; feedback in, tutorial
// refined; release note in, tutorial updated — without a live backend.
//
// Every function here mirrors the shape of a real backend workflow
// (design doc §14-17, §31): understand -> retrieve -> reason -> decide ->
// act -> record. When the real agent exists behind POST /api/events/*,
// these functions get replaced by fetch() calls; callers don't change.

import { store, nextId } from './store';
import type {
  AgentAction,
  IngestResult,
  KnowledgeGap,
  Ticket,
  Tutorial,
  TutorialVersion,
  ReleaseNote,
} from '../types';

const STOPWORDS = new Set([
  'the', 'a', 'an', 'is', 'are', 'how', 'do', 'does', 'i', 'to', 'for', 'of', 'in', 'on',
  'with', 'can', 'my', 'me', 'help', 'where', 'what', 'it', 'and', 'or', 'this', 'that',
  'you', 'your', 'am', 'be', 'was', 'were', 'not', 'have', 'has', 'never', 'up',
]);

function significantWords(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .filter((w) => w.length > 3 && !STOPWORDS.has(w)),
  );
}

function overlapScore(a: Set<string>, b: Set<string>): number {
  let score = 0;
  for (const w of a) if (b.has(w)) score++;
  return score;
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
    .slice(0, 40);
}

function nextTicketNumber(): number {
  const nums = store.tickets
    .map((t) => Number(t.id.match(/#(\d+)/)?.[1] ?? 0))
    .filter((n) => !Number.isNaN(n));
  return (nums.length ? Math.max(...nums) : 100) + 1;
}

function nextReleaseNumber(): number {
  const nums = store.releases
    .map((r) => Number(r.id.match(/#(\d+)/)?.[1] ?? 0))
    .filter((n) => !Number.isNaN(n));
  return (nums.length ? Math.max(...nums) : 44) + 1;
}

const RECURRING_THRESHOLD = 3;

function generateTutorialTemplate(topic: string, description: string): string {
  return `# ${topic}

## Overview

${description}

## Step 1

Open Copilot.

## Step 2

Select the feature related to "${topic}".

## Step 3

Follow the on-screen guidance to complete the task.

## Tips

This tutorial was auto-generated from recurring support tickets. Expect the agent to refine it as feedback comes in.`;
}

function createTutorialFromGap(gap: KnowledgeGap): { tutorial: Tutorial; version: TutorialVersion } {
  const now = new Date().toISOString();
  const tutorial: Tutorial = {
    id: nextId('tut'),
    title: gap.topic,
    slug: slugify(gap.topic),
    description: gap.description,
    feature_id: gap.feature_id,
    status: 'active',
    current_version_id: '',
    created_at: now,
    updated_at: now,
    average_rating: 0,
    rating_count: 0,
    version_count: 1,
  };
  const version: TutorialVersion = {
    id: nextId('tv'),
    tutorial_id: tutorial.id,
    version: 1,
    content: generateTutorialTemplate(gap.topic, gap.description),
    change_type: 'CREATE',
    change_reason: `Recurring knowledge gap detected across ${gap.evidence_count} support tickets.`,
    evidence: [...gap.source_tickets],
    outcome: 'Tutorial published.',
    created_at: now,
    created_by: 'agent',
  };
  tutorial.current_version_id = version.id;
  store.tutorials.push(tutorial);
  store.tutorialVersions.push(version);
  return { tutorial, version };
}

// ---- Ticket workflow (§14-15) ---------------------------------------------

export function ingestTicket(text: string): IngestResult {
  const trimmed = text.trim();
  if (!trimmed) return { message: 'Ticket text is empty.', agent_actions: [] };

  const now = new Date().toISOString();
  const ticket: Ticket = {
    id: `Ticket #${nextTicketNumber()}`,
    title: trimmed.slice(0, 80),
    description: trimmed,
    status: 'triaged',
    created_at: now,
  };

  const words = significantWords(trimmed);
  let bestGap: KnowledgeGap | null = null;
  let bestScore = 0;
  for (const gap of store.knowledgeGaps) {
    const score = overlapScore(words, significantWords(`${gap.topic} ${gap.description}`));
    if (score > bestScore) {
      bestScore = score;
      bestGap = gap;
    }
  }

  const actions: AgentAction[] = [];
  let message: string;

  if (bestGap && bestScore > 0 && bestGap.status === 'resolved') {
    ticket.matched_gap_id = bestGap.id;
    ticket.matched_gap_topic = bestGap.topic;
    const tutorial = store.tutorials.find((t) => t.id === bestGap!.resolved_tutorial_id);
    message = `Matched existing knowledge — "${tutorial?.title ?? bestGap.topic}" already covers this. No new gap created.`;
  } else if (bestGap && bestScore > 0) {
    bestGap.evidence_count += 1;
    bestGap.source_tickets.push(ticket.id);
    bestGap.last_detected_at = now;
    ticket.matched_gap_id = bestGap.id;
    ticket.matched_gap_topic = bestGap.topic;

    if (bestGap.evidence_count >= RECURRING_THRESHOLD && bestGap.status === 'candidate') {
      bestGap.status = 'recurring';
      const { tutorial, version } = createTutorialFromGap(bestGap);
      bestGap.status = 'resolved';
      bestGap.resolved_tutorial_id = tutorial.id;
      const action: AgentAction = {
        id: nextId('aa'),
        action_type: 'CREATE_TUTORIAL',
        target_type: 'tutorial_version',
        target_id: version.id,
        target_title: `${tutorial.title} v1`,
        decision: 'CREATE',
        reason: `Knowledge gap "${bestGap.topic}" became recurring after ${bestGap.evidence_count} related tickets.`,
        evidence: [...bestGap.source_tickets],
        outcome: `Tutorial "${tutorial.title}" v1 published.`,
        created_at: now,
      };
      store.agentActions.unshift(action);
      actions.push(action);
      message = `3rd related ticket detected — "${bestGap.topic}" promoted to recurring. Tutorial v1 created.`;
    } else {
      message = `Ticket matched candidate knowledge gap "${bestGap.topic}" (${bestGap.evidence_count}/${RECURRING_THRESHOLD} tickets so far).`;
    }
  } else {
    const gap: KnowledgeGap = {
      id: nextId('kg'),
      topic: trimmed.length > 48 ? `${trimmed.slice(0, 48)}…` : trimmed,
      description: trimmed,
      feature_id: `feat_${slugify(trimmed) || 'unknown'}`,
      status: 'candidate',
      evidence_count: 1,
      source_tickets: [ticket.id],
      first_detected_at: now,
      last_detected_at: now,
    };
    store.knowledgeGaps.push(gap);
    ticket.matched_gap_id = gap.id;
    ticket.matched_gap_topic = gap.topic;

    const action: AgentAction = {
      id: nextId('aa'),
      action_type: 'CREATE_KNOWLEDGE_GAP',
      target_type: 'knowledge_gap',
      target_id: gap.id,
      target_title: gap.topic,
      decision: 'CREATE',
      reason: 'No existing knowledge gap or tutorial matched this ticket closely enough.',
      evidence: [ticket.id],
      outcome: 'Marked as a candidate gap; will promote to a tutorial if it recurs.',
      created_at: now,
    };
    store.agentActions.unshift(action);
    actions.push(action);
    message = `No match found — new candidate knowledge gap "${gap.topic}" created (1/${RECURRING_THRESHOLD} tickets).`;
  }

  store.tickets.unshift(ticket);
  return { message, agent_actions: actions };
}

// ---- Release workflow (§17) ------------------------------------------------

const RENAME_PATTERNS = [
  /(.+?)\s+has been renamed to\s+(.+?)\.?\s*$/i,
  /(.+?)\s+was renamed to\s+(.+?)\.?\s*$/i,
  /(.+?)\s+is now (?:called |named )?(.+?)\.?\s*$/i,
  /(.+?)\s+renamed to\s+(.+?)\.?\s*$/i,
];

export function ingestReleaseNote(text: string): IngestResult {
  const trimmed = text.trim();
  if (!trimmed) return { message: 'Release note is empty.', agent_actions: [] };

  const now = new Date().toISOString();
  const release: ReleaseNote = {
    id: `Release #${nextReleaseNumber()}`,
    title: trimmed.length > 60 ? `${trimmed.slice(0, 60)}…` : trimmed,
    description: trimmed,
    release_date: now,
    status: 'processed',
    created_at: now,
  };
  store.releases.unshift(release);

  let match: RegExpMatchArray | null = null;
  for (const pattern of RENAME_PATTERNS) {
    match = trimmed.match(pattern);
    if (match) break;
  }

  if (!match) {
    return {
      message:
        'No rename pattern detected in this note. (A real agent would use the LLM for deeper extraction — this simulation only recognizes straightforward renames.)',
      agent_actions: [],
    };
  }

  const oldTerm = match[1].trim().replace(/^["']|["']$/g, '');
  const newTerm = match[2].trim().replace(/^["']|["']$/g, '');
  const escaped = oldTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const testRegex = () => new RegExp(escaped, 'i'); // fresh instance — no lastIndex state
  const replaceRegex = () => new RegExp(escaped, 'gi');

  const actions: AgentAction[] = [];
  let affected = 0;

  for (const tutorial of store.tutorials) {
    if (tutorial.status === 'retired') continue;
    const versions = store.tutorialVersions
      .filter((v) => v.tutorial_id === tutorial.id)
      .sort((a, b) => a.version - b.version);
    const current = versions[versions.length - 1];
    const mentionsTerm =
      current && (testRegex().test(current.content) || testRegex().test(tutorial.title) || testRegex().test(tutorial.description));
    if (!current || !mentionsTerm) continue;

    affected += 1;
    const newVersion: TutorialVersion = {
      id: nextId('tv'),
      tutorial_id: tutorial.id,
      version: current.version + 1,
      content: current.content.replace(replaceRegex(), newTerm),
      change_type: 'UPDATE',
      change_reason: `${release.id} renamed "${oldTerm}" to "${newTerm}".`,
      evidence: [release.id],
      outcome: `Tutorial is now aligned with the "${newTerm}" terminology.`,
      created_at: now,
      created_by: 'agent',
    };
    store.tutorialVersions.push(newVersion);
    tutorial.current_version_id = newVersion.id;
    tutorial.version_count += 1;
    tutorial.updated_at = now;
    // Keep the tutorial's own title/description in sync too, not just the
    // version body — otherwise the Hub card and page header go stale.
    tutorial.title = tutorial.title.replace(replaceRegex(), newTerm);
    tutorial.description = tutorial.description.replace(replaceRegex(), newTerm);

    const action: AgentAction = {
      id: nextId('aa'),
      action_type: 'UPDATE_TUTORIAL',
      target_type: 'tutorial_version',
      target_id: newVersion.id,
      target_title: `${tutorial.title} v${newVersion.version}`,
      decision: 'UPDATE',
      reason: newVersion.change_reason,
      evidence: [release.id],
      outcome: newVersion.outcome,
      created_at: now,
    };
    store.agentActions.unshift(action);
    actions.push(action);
  }

  const message = affected
    ? `Detected rename "${oldTerm}" → "${newTerm}". Updated ${affected} affected tutorial${affected === 1 ? '' : 's'}.`
    : `Detected rename "${oldTerm}" → "${newTerm}", but no tutorial currently mentions "${oldTerm}" — no changes made.`;

  return { message, agent_actions: actions };
}

// ---- Feedback workflow (§16) -----------------------------------------------

const NEGATIVE_FEEDBACK_THRESHOLD = 2;

export function reviewTutorial(tutorialId: string): IngestResult {
  const tutorial = store.tutorials.find((t) => t.id === tutorialId);
  if (!tutorial) return { message: 'Tutorial not found.', agent_actions: [] };

  const versions = store.tutorialVersions
    .filter((v) => v.tutorial_id === tutorialId)
    .sort((a, b) => a.version - b.version);
  const current = versions[versions.length - 1];
  const fb = store.feedback.filter((f) => f.tutorial_version_id === current.id);
  const negative = fb.filter((f) => f.rating <= 2);
  const avg = fb.length ? fb.reduce((s, f) => s + f.rating, 0) / fb.length : tutorial.average_rating;

  if (negative.length < NEGATIVE_FEEDBACK_THRESHOLD) {
    return {
      message: `"${tutorial.title}" doesn't have enough negative feedback yet to warrant a refinement (${negative.length} negative item${negative.length === 1 ? '' : 's'}, need ${NEGATIVE_FEEDBACK_THRESHOLD}+).`,
      agent_actions: [],
    };
  }

  const now = new Date().toISOString();
  const topComment = negative.map((f) => f.comment).find(Boolean);
  const reason = topComment
    ? `Users report: "${topComment}"`
    : 'Recent feedback indicates this tutorial is unclear.';

  const newVersion: TutorialVersion = {
    id: nextId('tv'),
    tutorial_id: tutorialId,
    version: current.version + 1,
    content: `${current.content}\n\n## Update\n\nThis tutorial was clarified based on recent user feedback.`,
    change_type: 'REFINE',
    change_reason: reason,
    evidence: [
      `${negative.length} negative feedback item${negative.length === 1 ? '' : 's'}`,
      `Average rating ${avg.toFixed(1)} / 5`,
    ],
    outcome: 'New version published; awaiting feedback to confirm improvement.',
    created_at: now,
    created_by: 'agent',
  };
  store.tutorialVersions.push(newVersion);
  tutorial.current_version_id = newVersion.id;
  tutorial.version_count += 1;
  tutorial.updated_at = now;
  tutorial.status = 'active';

  const action: AgentAction = {
    id: nextId('aa'),
    action_type: 'REFINE_TUTORIAL',
    target_type: 'tutorial_version',
    target_id: newVersion.id,
    target_title: `${tutorial.title} v${newVersion.version}`,
    decision: 'REFINE',
    reason,
    evidence: newVersion.evidence,
    outcome: newVersion.outcome,
    created_at: now,
  };
  store.agentActions.unshift(action);

  return { message: `"${tutorial.title}" refined to v${newVersion.version}.`, agent_actions: [action] };
}
