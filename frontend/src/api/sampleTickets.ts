// A pool of sample ticket text for the "🎲 Random ticket" button in the
// Incoming Tickets panel. Mostly unrelated IT-helpdesk noise (so presenters
// can show the agent correctly ignoring one-off, non-recurring issues
// instead of only ever feeding it hand-picked, on-topic tickets), plus a
// few on-topic ones mixed in for variety. Written by hand rather than
// pulled from an external dataset — see conversation for why.

export const SAMPLE_TICKETS: string[] = [
  // --- Noise: unrelated one-off issues, should stay "Unmatched" ---
  'My VPN keeps disconnecting every 10 minutes',
  'Can I get a second monitor for my desk?',
  'Outlook is not syncing my calendar invites',
  'How do I request more OneDrive storage?',
  'The printer on the 4th floor is out of toner again',
  'My laptop fan is really loud, can IT take a look?',
  'I need admin access to install a design tool',
  'Teams keeps crashing when I share my screen',
  'How do I set up an out-of-office auto-reply?',
  'Can someone reset my SSO password?',
  'My badge doesn\'t work on the east entrance anymore',
  'Is there a dark mode for the internal wiki?',
  'I was double-charged for my parking pass this month',
  'How do I add a delegate to my mailbox?',
  'The conference room booking system is showing double bookings',
  'Can I get a license for the new design software?',
  'My headset mic isn\'t picked up in calls anymore',
  'How do I export my expense report as a PDF?',

  // --- On-topic: should match an existing knowledge gap ---
  'How do I get Copilot to summarize my meeting?',
  'Can Copilot suggest talking points before a call with a customer?',
  'Is there a way to have Copilot build a PivotTable from my sales data?',
];

export function randomSampleTicket(exclude?: string): string {
  const pool = SAMPLE_TICKETS.filter((t) => t !== exclude);
  return pool[Math.floor(Math.random() * pool.length)] ?? SAMPLE_TICKETS[0];
}
