import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import type { Feedback, Tutorial, TutorialVersion } from '../../types';
import { getTutorial, getTutorialVersions, getFeedback, submitFeedback } from '../../api/client';
import TutorialViewer from '../../components/TutorialViewer';
import FeedbackForm from '../../components/FeedbackForm';
import StarRating from '../../components/StarRating';
import StatusBadge from '../../components/StatusBadge';

export default function TutorialDetailPage() {
  const { slug } = useParams<{ slug: string }>();
  const [tutorial, setTutorial] = useState<Tutorial | null | undefined>(undefined);
  const [versions, setVersions] = useState<TutorialVersion[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<Feedback[]>([]);

  useEffect(() => {
    if (!slug) return;
    getTutorial(slug).then((t) => {
      setTutorial(t ?? null);
      if (t) {
        getTutorialVersions(t.id).then((vs) => {
          setVersions(vs);
          setSelectedVersion(vs[vs.length - 1]?.version ?? null);
        });
        getFeedback(t.id).then(setFeedback);
      }
    });
  }, [slug]);

  if (tutorial === undefined) {
    return <div className="max-w-3xl mx-auto px-6 py-8 text-slate-400 text-sm">Loading…</div>;
  }
  if (tutorial === null) {
    return (
      <div className="max-w-3xl mx-auto px-6 py-8">
        <p className="text-slate-600">Tutorial not found.</p>
        <Link to="/tutorials" className="text-indigo-600 text-sm">
          ← Back to Tutorial Hub
        </Link>
      </div>
    );
  }

  const current = versions.find((v) => v.version === selectedVersion) ?? versions[versions.length - 1];

  const handleSubmit = async (rating: number, comment: string) => {
    if (!current) return;
    const entry = await submitFeedback(tutorial.id, current.id, rating, comment);
    setFeedback((prev) => [entry, ...prev]);
  };

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <Link to="/tutorials" className="text-sm text-slate-500 hover:text-slate-800">
        ← Back to Tutorial Hub
      </Link>

      <div className="flex items-start justify-between gap-3 mt-3">
        <h1 className="text-2xl font-semibold text-slate-900">{tutorial.title}</h1>
        <StatusBadge status={tutorial.status} />
      </div>

      <div className="flex flex-wrap items-center gap-4 mt-3 text-sm text-slate-500">
        {versions.length > 1 ? (
          <select
            value={selectedVersion ?? ''}
            onChange={(e) => setSelectedVersion(Number(e.target.value))}
            className="rounded-md border border-slate-200 px-2 py-1 text-sm bg-white"
          >
            {versions.map((v) => (
              <option key={v.id} value={v.version}>
                Version {v.version}
                {v.version === versions[versions.length - 1].version ? ' (current)' : ''}
              </option>
            ))}
          </select>
        ) : (
          <span>Version {versions[0]?.version ?? 1}</span>
        )}
        <div className="flex items-center gap-1.5">
          <StarRating value={tutorial.average_rating} size="sm" />
          <span>{tutorial.average_rating.toFixed(1)}</span>
        </div>
        <span>Last updated {new Date(tutorial.updated_at).toLocaleDateString()}</span>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6 mt-6">
        {current ? <TutorialViewer version={current} /> : <p className="text-slate-400 text-sm">No content.</p>}
      </div>

      <div className="mt-6">
        <FeedbackForm onSubmit={handleSubmit} />
      </div>

      {feedback.length > 0 && (
        <div className="mt-8">
          <h3 className="text-sm font-semibold text-slate-900 mb-3">
            Feedback on this tutorial ({feedback.length})
          </h3>
          <div className="space-y-3">
            {feedback.slice(0, 8).map((f) => (
              <div key={f.id} className="bg-white border border-slate-200 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <StarRating value={f.rating} size="sm" />
                  <span className="text-xs text-slate-400">
                    {new Date(f.created_at).toLocaleDateString()}
                  </span>
                </div>
                {f.comment && <p className="text-sm text-slate-600 mt-1.5">{f.comment}</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
