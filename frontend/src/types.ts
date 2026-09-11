// Shared types — mirror the backend data model (design doc §27) and API
// response shapes (§29) exactly, so the mock layer in src/api can later be
// swapped for real `fetch()` calls with zero changes to components.

export type TutorialStatus = 'active' | 'needs_review' | 'retired';

export interface Tutorial {
  id: string;
  title: string;
  slug: string;
  description: string;
  feature_id: string;
  status: TutorialStatus;
  current_version_id: string;
  created_at: string;
  updated_at: string;
  // Denormalized for list/card display (backed by Hotdata in the real system)
  average_rating: number;
  rating_count: number;
  version_count: number;
}

export type ChangeType = 'CREATE' | 'REFINE' | 'UPDATE' | 'RETIRE';

export interface TutorialVersion {
  id: string;
  tutorial_id: string;
  version: number;
  content: string; // markdown
  change_type: ChangeType;
  change_reason: string;
  evidence: string[];
  outcome?: string;
  created_at: string;
  created_by: 'agent' | 'human';
}

export interface Feedback {
  id: string;
  tutorial_id: string;
  tutorial_version_id: string;
  user_id: string;
  rating: number; // 1-5
  comment: string;
  created_at: string;
}

export type KnowledgeGapStatus = 'candidate' | 'recurring' | 'resolved' | 'ignored';

export interface KnowledgeGap {
  id: string;
  topic: string;
  description: string;
  feature_id: string;
  status: KnowledgeGapStatus;
  evidence_count: number;
  source_tickets: string[];
  first_detected_at: string;
  last_detected_at: string;
  resolved_tutorial_id?: string;
}

export type AgentActionType =
  | 'CREATE_KNOWLEDGE_GAP'
  | 'CREATE_TUTORIAL'
  | 'REFINE_TUTORIAL'
  | 'UPDATE_TUTORIAL'
  | 'RETIRE_TUTORIAL';

export interface AgentAction {
  id: string;
  action_type: AgentActionType;
  target_type: 'tutorial' | 'tutorial_version' | 'knowledge_gap';
  target_id: string;
  target_title: string;
  decision: 'NO_ACTION' | 'CREATE' | 'UPDATE' | 'REFINE' | 'RETIRE';
  reason: string;
  evidence: string[];
  outcome?: string;
  created_at: string;
}

export interface TutorialHealthPoint {
  version: number;
  average_rating: number;
  negative_feedback_count: number;
  related_ticket_count: number;
  outdated_steps: number;
}

export interface TutorialHealth {
  tutorial_id: string;
  tutorial_title: string;
  status: TutorialStatus;
  current_rating: number;
  related_tickets: number;
  negative_feedback: number;
  ai_analysis: string;
  recommended_action: 'NO_ACTION' | 'CREATE' | 'UPDATE' | 'REFINE' | 'RETIRE';
  history: TutorialHealthPoint[];
}

export interface VersionDiff {
  tutorial_id: string;
  from_version: number;
  to_version: number;
  diff_lines: { type: 'context' | 'added' | 'removed'; text: string }[];
  reason: string;
  evidence: string[];
  agent_action: string;
  outcome: string;
}

// ---- Event sources (§29 /api/events/*) ------------------------------------
// Tickets and release notes are ingestion inputs, not knowledge-base
// artifacts — they don't get a browsing page, but the Improvement Console
// needs to show them arriving and show the agent reacting to them.

export interface Ticket {
  id: string;
  title: string;
  description: string;
  status: 'new' | 'triaged';
  matched_gap_id?: string;
  matched_gap_topic?: string;
  created_at: string;
}

export interface ReleaseNote {
  id: string;
  title: string;
  description: string;
  release_date: string;
  status: 'new' | 'processed';
  created_at: string;
}

// Result of an ingestion call — lets the UI narrate what the agent just did.
export interface IngestResult {
  message: string;
  agent_actions: AgentAction[];
}
