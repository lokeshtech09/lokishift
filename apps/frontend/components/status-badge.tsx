import { Check, Loader2 } from 'lucide-react';
import type { TaskStatus } from '@/lib/api';
import { cn } from '@/lib/utils';

/*
 * Calm status chips: a neutral pill with one small signal (dot, spinner or
 * check). Red appears only as the small dot on "Ready to tailor" (your
 * move) and on failures.
 */
const STYLES: Record<
  TaskStatus,
  { label: string; chip: string; signal: 'spin' | 'dot' | 'check'; tone: string }
> = {
  matching: {
    label: 'Matching',
    chip: 'bg-gray-100 text-gray-700',
    signal: 'spin',
    tone: 'text-brand-500',
  },
  matched: {
    label: 'Ready to tailor',
    chip: 'bg-white text-brand-800 ring-1 ring-inset ring-brand-200',
    signal: 'dot',
    tone: 'bg-accent-500',
  },
  tailoring: {
    label: 'Tailoring',
    chip: 'bg-gray-100 text-gray-700',
    signal: 'spin',
    tone: 'text-brand-500',
  },
  finished: {
    label: 'Finished',
    chip: 'bg-brand-100 text-brand-800',
    signal: 'check',
    tone: 'text-brand-600',
  },
  failed: { label: 'Failed', chip: 'bg-red-50 text-red-700', signal: 'dot', tone: 'bg-red-500' },
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  const s = STYLES[status];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold',
        s.chip
      )}
    >
      {s.signal === 'spin' && <Loader2 className={cn('h-3 w-3 animate-spin', s.tone)} />}
      {s.signal === 'dot' && <span className={cn('h-1.5 w-1.5 rounded-full', s.tone)} />}
      {s.signal === 'check' && <Check className={cn('h-3 w-3', s.tone)} strokeWidth={3} />}
      {s.label}
    </span>
  );
}

/** Match score: solid grey when strong, outlined when middling, soft red when weak. */
export function ScorePill({ score, muted }: { score: number | null | undefined; muted?: boolean }) {
  if (score === null || score === undefined)
    return <span className="text-sm text-gray-400">—</span>;
  const tone = muted
    ? 'text-gray-500 bg-gray-100'
    : score >= 80
      ? 'text-brand-900 bg-brand-100'
      : score >= 60
        ? 'text-gray-600 bg-gray-50 ring-1 ring-inset ring-gray-200'
        : 'text-red-700 bg-red-50';
  return (
    <span
      className={cn('inline-block rounded-md px-2 py-0.5 text-sm font-semibold tabular-nums', tone)}
    >
      {score}%
    </span>
  );
}
