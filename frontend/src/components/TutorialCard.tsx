import { Link } from 'react-router-dom';
import type { Tutorial } from '../types';
import StarRating from './StarRating';
import StatusBadge from './StatusBadge';

export default function TutorialCard({ tutorial }: { tutorial: Tutorial }) {
  return (
    <Link
      to={`/tutorials/${tutorial.slug}`}
      className="block bg-white border border-slate-200 rounded-xl p-5 hover:border-indigo-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold text-slate-900">{tutorial.title}</h3>
        <StatusBadge status={tutorial.status} />
      </div>
      <p className="text-sm text-slate-600 mt-1.5 line-clamp-2">{tutorial.description}</p>
      <div className="flex items-center justify-between mt-4">
        <div className="flex items-center gap-1.5">
          <StarRating value={tutorial.average_rating} size="sm" />
          <span className="text-xs text-slate-500">
            {tutorial.average_rating.toFixed(1)} ({tutorial.rating_count})
          </span>
        </div>
        <span className="text-xs text-slate-400">Version {tutorial.version_count}</span>
      </div>
    </Link>
  );
}
