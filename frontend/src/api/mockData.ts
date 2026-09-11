import type {
  Tutorial,
  TutorialVersion,
  Feedback,
  KnowledgeGap,
  AgentAction,
  Ticket,
  ReleaseNote,
} from '../types';

// ---------------------------------------------------------------------------
// Seed data for the end-to-end demo scenario from the design doc (§34-37):
// Meeting Preparation goes ticket -> knowledge gap -> v1 -> feedback -> v2
// -> release note -> v3. Two extra tutorials round out the Hub / Console.
// ---------------------------------------------------------------------------

export const tutorials: Tutorial[] = [
  {
    id: 'tut_meeting_prep',
    title: 'Meeting Preparation',
    slug: 'meeting-preparation',
    description: 'Use Copilot to prepare for your upcoming meetings with summaries and suggested talking points.',
    feature_id: 'feat_prepare',
    status: 'active',
    current_version_id: 'tv_meeting_prep_3',
    created_at: '2026-08-02T09:00:00Z',
    updated_at: '2026-09-10T14:20:00Z',
    average_rating: 4.5,
    rating_count: 26,
    version_count: 3,
  },
  {
    id: 'tut_chat_basics',
    title: 'Getting Started with Copilot Chat',
    slug: 'copilot-chat-basics',
    description: 'Learn the basics of chatting with Copilot: prompts, references, and follow-up questions.',
    feature_id: 'feat_chat',
    status: 'active',
    current_version_id: 'tv_chat_basics_1',
    created_at: '2026-07-14T10:00:00Z',
    updated_at: '2026-07-14T10:00:00Z',
    average_rating: 4.7,
    rating_count: 41,
    version_count: 1,
  },
  {
    id: 'tut_excel_summarize',
    title: 'Summarizing Data in Excel with Copilot',
    slug: 'copilot-excel-summarize',
    description: 'Ask Copilot to summarize and highlight trends in an Excel worksheet.',
    feature_id: 'feat_excel',
    status: 'needs_review',
    current_version_id: 'tv_excel_summarize_1',
    created_at: '2026-08-20T11:00:00Z',
    updated_at: '2026-08-20T11:00:00Z',
    average_rating: 2.8,
    rating_count: 12,
    version_count: 1,
  },
];

export const tutorialVersions: TutorialVersion[] = [
  {
    id: 'tv_meeting_prep_1',
    tutorial_id: 'tut_meeting_prep',
    version: 1,
    change_type: 'CREATE',
    change_reason: 'Recurring knowledge gap detected across 3 support tickets about meeting preparation.',
    evidence: ['Ticket #101', 'Ticket #145', 'Ticket #192'],
    outcome: 'Tutorial published. Users began rating and commenting.',
    created_at: '2026-08-02T09:00:00Z',
    created_by: 'agent',
    content: `# Meeting Preparation

## Overview

Use Copilot to prepare for your upcoming meeting.

## Step 1

Open Copilot.

## Step 2

Select the meeting.

## Step 3

Open Meeting Summary.

## Tips

Copilot works best when your calendar invite includes an agenda.`,
  },
  {
    id: 'tv_meeting_prep_2',
    tutorial_id: 'tut_meeting_prep',
    version: 2,
    change_type: 'REFINE',
    change_reason: 'Step 3 is frequently reported as unclear. Users could not locate the button.',
    evidence: ['8 negative feedback items', '3 related support tickets', 'Average rating 2.9 / 5'],
    outcome: 'Average rating improved from 2.9 to 4.4. Negative feedback dropped from 8 to 2.',
    created_at: '2026-08-22T13:10:00Z',
    created_by: 'agent',
    content: `# Meeting Preparation

## Overview

Use Copilot to prepare for your upcoming meeting.

## Step 1

Open Copilot.

## Step 2

Select the meeting from your calendar in the left panel.

## Step 3

Open Meeting Summary from the meeting card. This shows key talking points, prior action items, and suggested prep questions based on your calendar and recent emails.

## Tips

Copilot works best when your calendar invite includes an agenda. If Meeting Summary doesn't appear, confirm Copilot is enabled for your calendar in Settings.`,
  },
  {
    id: 'tv_meeting_prep_3',
    tutorial_id: 'tut_meeting_prep',
    version: 3,
    change_type: 'UPDATE',
    change_reason: 'Product Release #45 renamed Meeting Summary to Prepare.',
    evidence: ['Release Note #45'],
    outcome: 'Tutorial is now aligned with the current UI.',
    created_at: '2026-09-10T14:20:00Z',
    created_by: 'agent',
    content: `# Meeting Preparation

## Overview

Use Copilot to prepare for your upcoming meeting.

## Step 1

Open Copilot.

## Step 2

Select the meeting from your calendar in the left panel.

## Step 3

Open Prepare from the meeting card. This shows key talking points, prior action items, and suggested prep questions based on your calendar and recent emails.

## Tips

Copilot works best when your calendar invite includes an agenda. If Prepare doesn't appear, confirm Copilot is enabled for your calendar in Settings.`,
  },
  {
    id: 'tv_chat_basics_1',
    tutorial_id: 'tut_chat_basics',
    version: 1,
    change_type: 'CREATE',
    change_reason: 'Recurring onboarding questions about how to start a Copilot Chat conversation.',
    evidence: ['Ticket #58', 'Ticket #64'],
    created_at: '2026-07-14T10:00:00Z',
    created_by: 'agent',
    content: `# Getting Started with Copilot Chat

## Overview

Copilot Chat lets you ask questions in natural language and get answers grounded in your work data.

## Step 1

Open Copilot Chat from the sidebar.

## Step 2

Type your question. Use "/" to reference a file, email, or meeting.

## Step 3

Ask follow-up questions — Copilot remembers the conversation.

## Tips

Be specific. "Summarize the Q3 deck" works better than "summarize this".`,
  },
  {
    id: 'tv_excel_summarize_1',
    tutorial_id: 'tut_excel_summarize',
    version: 1,
    change_type: 'CREATE',
    change_reason: 'Recurring questions about analyzing spreadsheets with Copilot.',
    evidence: ['Ticket #210', 'Ticket #233', 'Ticket #240'],
    created_at: '2026-08-20T11:00:00Z',
    created_by: 'agent',
    content: `# Summarizing Data in Excel with Copilot

## Overview

Ask Copilot to summarize and highlight trends in a worksheet.

## Step 1

Open your workbook and select a data range.

## Step 2

Open Copilot in the ribbon.

## Step 3

Ask "Summarize this data" or "Highlight the top 5 rows by revenue".

## Tips

Copilot works best on data with headers in row 1.`,
  },
];

export const feedback: Feedback[] = [
  // v1 feedback — mostly negative, centered on Step 3
  { id: 'fb1', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_442', rating: 2, comment: 'Step 3 is confusing.', created_at: '2026-08-05T10:00:00Z' },
  { id: 'fb2', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_118', rating: 2, comment: "Can't find the button.", created_at: '2026-08-06T09:30:00Z' },
  { id: 'fb3', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_301', rating: 1, comment: 'The UI looks different from the screenshots.', created_at: '2026-08-07T15:45:00Z' },
  { id: 'fb4', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_552', rating: 3, comment: 'Steps 1 and 2 were clear, step 3 was not.', created_at: '2026-08-08T11:20:00Z' },
  { id: 'fb5', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_213', rating: 2, comment: 'Where exactly is Meeting Summary?', created_at: '2026-08-09T08:10:00Z' },
  { id: 'fb6', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_601', rating: 4, comment: 'Mostly helpful, just step 3 needs more detail.', created_at: '2026-08-10T13:00:00Z' },
  { id: 'fb7', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_089', rating: 2, comment: 'Confusing wording on the last step.', created_at: '2026-08-11T16:30:00Z' },
  { id: 'fb8', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_1', user_id: 'employee_377', rating: 3, comment: 'Good overview but the button is hard to locate.', created_at: '2026-08-12T10:15:00Z' },
  // v2 feedback — much more positive after refinement
  { id: 'fb9', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_2', user_id: 'employee_442', rating: 5, comment: 'Much clearer now, found it right away.', created_at: '2026-08-25T09:00:00Z' },
  { id: 'fb10', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_2', user_id: 'employee_118', rating: 5, comment: 'Great, thanks!', created_at: '2026-08-26T10:00:00Z' },
  { id: 'fb11', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_2', user_id: 'employee_775', rating: 4, comment: 'Works well.', created_at: '2026-08-27T11:00:00Z' },
  { id: 'fb12', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_2', user_id: 'employee_090', rating: 2, comment: "The button is now called something else? Doesn't match.", created_at: '2026-09-08T14:00:00Z' },
  { id: 'fb13', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_2', user_id: 'employee_334', rating: 4, comment: 'Solid instructions.', created_at: '2026-09-01T09:00:00Z' },
  // v3 feedback — post release fix
  { id: 'fb14', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_3', user_id: 'employee_090', rating: 5, comment: 'Matches the UI now, perfect.', created_at: '2026-09-11T08:00:00Z' },
  { id: 'fb15', tutorial_id: 'tut_meeting_prep', tutorial_version_id: 'tv_meeting_prep_3', user_id: 'employee_512', rating: 5, comment: 'Nice and quick.', created_at: '2026-09-11T09:30:00Z' },
  // chat basics
  { id: 'fb16', tutorial_id: 'tut_chat_basics', tutorial_version_id: 'tv_chat_basics_1', user_id: 'employee_118', rating: 5, comment: 'Simple and clear.', created_at: '2026-07-15T10:00:00Z' },
  // excel — needs review
  { id: 'fb17', tutorial_id: 'tut_excel_summarize', tutorial_version_id: 'tv_excel_summarize_1', user_id: 'employee_442', rating: 2, comment: 'Copilot button was not in the ribbon for me.', created_at: '2026-08-22T10:00:00Z' },
  { id: 'fb18', tutorial_id: 'tut_excel_summarize', tutorial_version_id: 'tv_excel_summarize_1', user_id: 'employee_301', rating: 3, comment: 'Steps are a bit generic.', created_at: '2026-08-24T10:00:00Z' },
  { id: 'fb19', tutorial_id: 'tut_excel_summarize', tutorial_version_id: 'tv_excel_summarize_1', user_id: 'employee_559', rating: 1, comment: 'Step 2 button is missing on my ribbon layout.', created_at: '2026-08-26T09:00:00Z' },
];

export const knowledgeGaps: KnowledgeGap[] = [
  {
    id: 'kg_meeting_prep',
    topic: 'Meeting Preparation',
    description: 'Users repeatedly ask how to prepare for meetings and where meeting summaries appear.',
    feature_id: 'feat_prepare',
    status: 'resolved',
    evidence_count: 3,
    source_tickets: ['Ticket #101', 'Ticket #145', 'Ticket #192'],
    first_detected_at: '2026-07-28T09:00:00Z',
    last_detected_at: '2026-08-01T17:00:00Z',
    resolved_tutorial_id: 'tut_meeting_prep',
  },
  {
    id: 'kg_excel_pivot',
    topic: 'Building PivotTables with Copilot',
    description: 'A few users have asked whether Copilot can build PivotTables directly, but volume is still low.',
    feature_id: 'feat_excel',
    status: 'candidate',
    evidence_count: 2,
    source_tickets: ['Ticket #260', 'Ticket #266'],
    first_detected_at: '2026-09-05T09:00:00Z',
    last_detected_at: '2026-09-09T12:00:00Z',
  },
];

export const agentActions: AgentAction[] = [
  {
    id: 'aa1',
    action_type: 'CREATE_KNOWLEDGE_GAP',
    target_type: 'knowledge_gap',
    target_id: 'kg_meeting_prep',
    target_title: 'Meeting Preparation',
    decision: 'CREATE',
    reason: 'Three support tickets asked semantically similar questions about meeting preparation within a 5-day window.',
    evidence: ['Ticket #101', 'Ticket #145', 'Ticket #192'],
    outcome: 'Knowledge gap marked recurring and promoted for tutorial generation.',
    created_at: '2026-08-01T17:05:00Z',
  },
  {
    id: 'aa2',
    action_type: 'CREATE_TUTORIAL',
    target_type: 'tutorial_version',
    target_id: 'tv_meeting_prep_1',
    target_title: 'Meeting Preparation v1',
    decision: 'CREATE',
    reason: 'Recurring knowledge gap "Meeting Preparation" had no existing tutorial covering it.',
    evidence: ['Knowledge Gap: Meeting Preparation (recurring)'],
    outcome: 'Meeting Preparation v1 published.',
    created_at: '2026-08-02T09:00:00Z',
  },
  {
    id: 'aa3',
    action_type: 'REFINE_TUTORIAL',
    target_type: 'tutorial_version',
    target_id: 'tv_meeting_prep_2',
    target_title: 'Meeting Preparation v2',
    decision: 'REFINE',
    reason: 'Step 3 is frequently reported as unclear.',
    evidence: ['8 negative feedback items', '3 related support tickets', 'Average rating 2.9 / 5'],
    outcome: 'Average rating improved from 2.9 to 4.4. Negative feedback dropped from 8 to 2.',
    created_at: '2026-08-22T13:10:00Z',
  },
  {
    id: 'aa4',
    action_type: 'UPDATE_TUTORIAL',
    target_type: 'tutorial_version',
    target_id: 'tv_meeting_prep_3',
    target_title: 'Meeting Preparation v3',
    decision: 'UPDATE',
    reason: 'Product Release #45 renamed Meeting Summary to Prepare.',
    evidence: ['Release Note #45'],
    outcome: 'Tutorial is now aligned with current UI.',
    created_at: '2026-09-10T14:20:00Z',
  },
  {
    id: 'aa5',
    action_type: 'CREATE_TUTORIAL',
    target_type: 'tutorial_version',
    target_id: 'tv_excel_summarize_1',
    target_title: 'Summarizing Data in Excel with Copilot v1',
    decision: 'CREATE',
    reason: 'Recurring knowledge gap about summarizing spreadsheet data.',
    evidence: ['Ticket #210', 'Ticket #233', 'Ticket #240'],
    outcome: 'Tutorial published; early ratings are mixed (2.8 avg) — flagged for review.',
    created_at: '2026-08-20T11:00:00Z',
  },
];

// ---------------------------------------------------------------------------
// Tickets — the raw events that fed the knowledge gaps above, plus a couple
// of unrelated one-offs to show the agent correctly ignoring noise.
// ---------------------------------------------------------------------------

export const tickets: Ticket[] = [
  { id: 'Ticket #101', title: 'How do I prepare for a meeting?', description: 'How do I prepare for a meeting?', status: 'triaged', matched_gap_id: 'kg_meeting_prep', matched_gap_topic: 'Meeting Preparation', created_at: '2026-07-28T09:10:00Z' },
  { id: 'Ticket #145', title: 'Where is Meeting Summary?', description: 'Where is Meeting Summary?', status: 'triaged', matched_gap_id: 'kg_meeting_prep', matched_gap_topic: 'Meeting Preparation', created_at: '2026-07-30T14:00:00Z' },
  { id: 'Ticket #192', title: 'How can Copilot help with customer meetings?', description: 'How can Copilot help with customer meetings?', status: 'triaged', matched_gap_id: 'kg_meeting_prep', matched_gap_topic: 'Meeting Preparation', created_at: '2026-08-01T17:00:00Z' },
  { id: 'Ticket #260', title: 'Can Copilot build a PivotTable for me?', description: 'Can Copilot build a PivotTable for me?', status: 'triaged', matched_gap_id: 'kg_excel_pivot', matched_gap_topic: 'Building PivotTables with Copilot', created_at: '2026-09-05T09:00:00Z' },
  { id: 'Ticket #266', title: 'Asked Copilot to make a pivot table, nothing happened', description: 'Asked Copilot to make a pivot table, nothing happened', status: 'triaged', matched_gap_id: 'kg_excel_pivot', matched_gap_topic: 'Building PivotTables with Copilot', created_at: '2026-09-09T12:00:00Z' },
  { id: 'Ticket #305', title: 'My password reset email never arrived', description: 'My password reset email never arrived', status: 'triaged', created_at: '2026-09-02T10:00:00Z' },
  { id: 'Ticket #311', title: 'Copilot license not showing up after purchase', description: 'Copilot license not showing up after purchase', status: 'triaged', created_at: '2026-09-04T08:30:00Z' },
];

// ---------------------------------------------------------------------------
// Product releases — Release #45 is the one already reflected in Meeting
// Preparation v3. New ones can be submitted live from the Improvement
// Console to demo the release workflow.
// ---------------------------------------------------------------------------

export const releases: ReleaseNote[] = [
  {
    id: 'Release #45',
    title: 'Meeting Summary renamed to Prepare',
    description: 'Meeting Summary has been renamed to Prepare.',
    release_date: '2026-09-10T00:00:00Z',
    status: 'processed',
    created_at: '2026-09-10T14:15:00Z',
  },
];
