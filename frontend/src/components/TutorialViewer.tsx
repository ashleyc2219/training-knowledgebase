import ReactMarkdown from 'react-markdown';
import type { TutorialVersion } from '../types';

export default function TutorialViewer({ version }: { version: TutorialVersion }) {
  return (
    <article className="prose-tutorial">
      <ReactMarkdown>{version.content}</ReactMarkdown>
    </article>
  );
}
