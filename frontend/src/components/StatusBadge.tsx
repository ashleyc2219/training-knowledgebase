const STYLES: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700',
  needs_review: 'bg-amber-100 text-amber-700',
  retired: 'bg-slate-200 text-slate-600',
  candidate: 'bg-slate-100 text-slate-600',
  recurring: 'bg-amber-100 text-amber-700',
  resolved: 'bg-emerald-100 text-emerald-700',
  ignored: 'bg-slate-200 text-slate-500',
};

const LABELS: Record<string, string> = {
  active: 'Active',
  needs_review: 'Needs Improvement',
  retired: 'Retired',
  candidate: 'Candidate',
  recurring: 'Recurring',
  resolved: 'Resolved',
  ignored: 'Ignored',
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
        STYLES[status] ?? 'bg-slate-100 text-slate-600'
      }`}
    >
      {LABELS[status] ?? status}
    </span>
  );
}
