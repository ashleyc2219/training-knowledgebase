interface Props {
  value: number; // 0-5, can be fractional for display
  size?: 'sm' | 'md' | 'lg';
  interactive?: boolean;
  onChange?: (value: number) => void;
}

const SIZE_CLASSES = { sm: 'text-sm', md: 'text-lg', lg: 'text-2xl' };

export default function StarRating({ value, size = 'md', interactive = false, onChange }: Props) {
  const stars = [1, 2, 3, 4, 5];
  return (
    <div className={`inline-flex gap-0.5 ${SIZE_CLASSES[size]}`}>
      {stars.map((star) => {
        const filled = star <= Math.round(value);
        return (
          <span
            key={star}
            role={interactive ? 'button' : undefined}
            onClick={interactive ? () => onChange?.(star) : undefined}
            className={`leading-none ${filled ? 'text-amber-400' : 'text-slate-300'} ${
              interactive ? 'cursor-pointer hover:scale-110 transition-transform' : ''
            }`}
          >
            ★
          </span>
        );
      })}
    </div>
  );
}
