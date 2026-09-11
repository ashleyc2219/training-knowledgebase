import { useState } from 'react';
import StarRating from './StarRating';

interface Props {
  onSubmit: (rating: number, comment: string) => Promise<void>;
}

export default function FeedbackForm({ onSubmit }: Props) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async () => {
    if (rating === 0) return;
    setSubmitting(true);
    await onSubmit(rating, comment);
    setSubmitting(false);
    setSubmitted(true);
  };

  if (submitted) {
    return (
      <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4 text-sm text-emerald-800">
        Thanks for your feedback — it'll be reviewed the next time the agent analyzes this tutorial.
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5">
      <h4 className="font-medium text-slate-900 mb-1">Was this tutorial helpful?</h4>
      <p className="text-sm text-slate-500 mb-3">Your rating and comments help the agent improve future versions.</p>
      <StarRating value={rating} size="lg" interactive onChange={setRating} />
      <textarea
        className="mt-3 w-full rounded-lg border border-slate-200 p-3 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        rows={3}
        placeholder="Optional: what worked, what didn't?"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
      />
      <button
        onClick={handleSubmit}
        disabled={rating === 0 || submitting}
        className="mt-3 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-indigo-700 transition-colors"
      >
        {submitting ? 'Submitting…' : 'Submit Feedback'}
      </button>
    </div>
  );
}
