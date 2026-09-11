// In-memory mutable store backing the mock API (src/api/client.ts) and the
// simulated agent (src/api/agentEngine.ts). Stands in for HydraDB — every
// piece of code here talks to `store.*`, never the frozen seed arrays
// directly, so a real backend swap only touches client.ts / agentEngine.ts.

import {
  tutorials,
  tutorialVersions,
  feedback,
  knowledgeGaps,
  agentActions,
  tickets,
  releases,
} from './mockData';
import type {
  Tutorial,
  TutorialVersion,
  Feedback,
  KnowledgeGap,
  AgentAction,
  Ticket,
  ReleaseNote,
} from '../types';

export const store: {
  tutorials: Tutorial[];
  tutorialVersions: TutorialVersion[];
  feedback: Feedback[];
  knowledgeGaps: KnowledgeGap[];
  agentActions: AgentAction[];
  tickets: Ticket[];
  releases: ReleaseNote[];
} = {
  tutorials: [...tutorials],
  tutorialVersions: [...tutorialVersions],
  feedback: [...feedback],
  knowledgeGaps: [...knowledgeGaps],
  agentActions: [...agentActions],
  tickets: [...tickets],
  releases: [...releases],
};

let counter = 0;
export function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}_${Date.now()}_${counter}`;
}
