'use client';

import { CheckCircle2, Layers, Plus, Wand2, XCircle } from 'lucide-react';
import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { useActivity } from '@/components/activity-provider';
import { TaskTable } from '@/components/task-table';
import { SetupBanner } from '@/components/setup-banner';
import { buttonClass, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from '@/components/ui';
import { api, type DashboardStats, type Period, PERIODS, periodRange, type Task } from '@/lib/api';
import { cn } from '@/lib/utils';

export default function DashboardPage() {
  const { dashboard, version, refresh } = useActivity();
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [candidates, setCandidates] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>('this_week');
  const [status, setStatus] = useState('');

  const load = useCallback(async () => {
    try {
      const [list, profiles] = await Promise.all([
        api.listTasks({ limit: 50, status: status || undefined, ...periodRange(period) }),
        api.listProfiles(),
      ]);
      setTasks(list);
      setCandidates(Object.fromEntries(profiles.map((p) => [p.profile_id, p.full_name])));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load tasks.');
    }
  }, [period, status]);

  useEffect(() => {
    load();
  }, [load, version]);

  const periodLabel = PERIODS.find((p) => p.value === period)!.label.toLowerCase();
  const filtered = period !== 'all' || status !== '';

  const stats = dashboard?.stats;

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Track your resume tasks and stay organized." />

      <SetupBanner />
      <div className="grid grid-cols-3 gap-3 sm:gap-5">
        <StatCard label="Total Tasks" value={stats?.total} icon={Layers} tone="slate" />
        <StatCard label="Completed" value={stats?.completed} icon={CheckCircle2} tone="green" />
        <StatCard label="Failed" value={stats?.failed} icon={XCircle} tone="red" />
      </div>

      {stats && <PipelineCard stats={stats} />}

      <Card className="mt-8">
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <div className="mr-auto flex items-baseline gap-3">
            <h2 className="font-display text-lg font-semibold text-gray-900">Your tasks</h2>
            <Link
              href="/tasks"
              className="text-sm font-semibold text-brand-800 underline-offset-4 hover:text-accent-600 hover:underline"
            >
              View all
            </Link>
          </div>
          <div
            className="no-scrollbar flex max-w-full overflow-x-auto rounded-xl bg-gray-100 p-1"
            role="tablist"
            aria-label="Period"
          >
            {PERIODS.map((p) => (
              <button
                key={p.value}
                role="tab"
                aria-selected={period === p.value}
                onClick={() => setPeriod(p.value)}
                className={cn(
                  'whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition',
                  period === p.value
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-500 hover:text-gray-800'
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="Status"
            className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:border-brand-400 focus:outline-none focus:ring-4 focus:ring-brand-100"
          >
            <option value="">All statuses</option>
            <option value="matched">Ready to tailor</option>
            <option value="running">Running</option>
            <option value="finished">Finished</option>
            <option value="failed">Failed</option>
          </select>
        </div>
        <ErrorBanner message={error} />
        {tasks === null && !error ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : tasks && tasks.length === 0 && filtered ? (
          <EmptyState
            title={`No ${status ? 'matching ' : ''}tasks ${period === 'all' ? 'yet' : periodLabel}`}
            body={
              period === 'this_week'
                ? 'Nothing created since Monday. See all your tasks, or start a new one.'
                : 'Try another period or status.'
            }
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <button
                  onClick={() => {
                    setPeriod('all');
                    setStatus('');
                  }}
                  className={buttonClass('secondary', 'sm')}
                >
                  Show all time
                </button>
                <Link href="/tasks/new" className={buttonClass('primary', 'sm')}>
                  <Plus className="h-4 w-4" />
                  New Resume Task
                </Link>
              </div>
            }
          />
        ) : tasks && tasks.length === 0 ? (
          stats && stats.resumes === 0 ? (
            <EmptyState
              title="Start with a profile"
              body="Create a profile for a job title (e.g. Python Developer) and upload your resumes to it. Then create a task with a job description."
              action={
                <Link href="/profiles" className={buttonClass('primary')}>
                  Create a profile
                </Link>
              }
            />
          ) : (
            <EmptyState
              title="No tasks yet"
              body="Paste a job description and LokiShift picks your best resume and tailors it."
              action={
                <Link href="/tasks/new" className={buttonClass('primary')}>
                  <Plus className="h-4 w-4" />
                  New Resume Task
                </Link>
              }
            />
          )
        ) : (
          tasks && (
            <TaskTable
              tasks={tasks}
              candidates={candidates}
              onChanged={() => {
                load();
                refresh();
              }}
            />
          )
        )}
      </Card>
    </>
  );
}

const TONES = {
  slate: { ring: 'bg-gray-100 text-gray-500', bar: 'bg-gray-200' },
  green: { ring: 'bg-brand-100 text-brand-700', bar: 'bg-brand-300' },
  red: { ring: 'bg-red-50 text-red-500', bar: 'bg-red-300' },
};

function StatCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value?: number;
  icon: React.ComponentType<{ className?: string }>;
  tone: keyof typeof TONES;
}) {
  const t = TONES[tone];
  return (
    <div className="relative overflow-hidden rounded-2xl bg-white p-3.5 sm:p-6 shadow-[0_1px_2px_rgba(16,48,42,0.04),0_8px_24px_-12px_rgba(16,48,42,0.12)] ring-1 ring-black/5">
      <span className={cn('absolute inset-x-0 top-0 h-1', t.bar)} />
      <div className="flex items-center justify-between">
        <p className="truncate text-xs font-semibold text-gray-500 sm:text-sm">{label}</p>
        <span
          className={cn('hidden h-9 w-9 items-center justify-center rounded-xl sm:flex', t.ring)}
        >
          <Icon className="h-5 w-5" />
        </span>
      </div>
      <p className="mt-1.5 font-display text-2xl font-extrabold tabular-nums text-gray-900 sm:mt-3 sm:text-4xl">
        {value ?? '–'}
      </p>
    </div>
  );
}

/*
 * Where every task stands, as one segmented bar. Segments use the theme's
 * quiet scale: running is a pale animated grey, ready-to-tailor carries the
 * red "your move" accent, finished is solid Underground, failed soft red.
 */
function PipelineCard({ stats }: { stats: DashboardStats }) {
  const segments = [
    {
      key: 'finished',
      label: 'Finished',
      value: stats.completed,
      bar: 'bg-brand-500',
      dot: 'bg-brand-500',
      href: '/tasks?status=finished',
    },
    {
      key: 'ready',
      label: 'Ready to tailor',
      value: stats.ready_to_tailor,
      bar: 'bg-accent-200',
      dot: 'bg-accent-500',
      href: '/tasks?status=matched',
    },
    {
      key: 'running',
      label: 'Running',
      value: stats.in_progress,
      bar: 'bg-brand-200 animate-pulse',
      dot: 'bg-brand-300',
      href: '/tasks?status=running',
    },
    {
      key: 'failed',
      label: 'Failed',
      value: stats.failed,
      bar: 'bg-red-200',
      dot: 'bg-red-400',
      href: '/tasks?status=failed',
    },
  ];
  const total = stats.total;
  const done = total ? Math.round((stats.completed / total) * 100) : 0;

  return (
    <Card className="mt-8">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="font-display text-lg font-semibold text-gray-900">Task pipeline</h2>
          <p className="text-sm text-gray-500">
            {total ? `${done}% of your tasks are tailored` : 'Your tasks will show up here'}
            {stats.week_count > 0 && ` · ${stats.week_count} created this week`}
          </p>
        </div>
        {stats.ready_to_tailor > 0 && (
          <Link
            href="/tasks?status=matched"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-brand-800 underline-offset-4 hover:text-accent-600 hover:underline"
          >
            <Wand2 className="h-4 w-4" />
            Tailor {stats.ready_to_tailor} waiting
          </Link>
        )}
      </div>

      <div
        className="mt-4 flex h-3 gap-0.5 overflow-hidden rounded-full bg-gray-100"
        role="img"
        aria-label="Task pipeline"
      >
        {total > 0 &&
          segments
            .filter((s) => s.value > 0)
            .map((s) => (
              <div
                key={s.key}
                title={`${s.label}: ${s.value}`}
                className={cn('h-full transition-all duration-500', s.bar)}
                style={{ width: `${(s.value / total) * 100}%` }}
              />
            ))}
      </div>

      <div className="mt-4 flex flex-wrap gap-x-2 gap-y-1">
        {segments.map((s) => (
          <Link
            key={s.key}
            href={s.href}
            className="flex items-center gap-2 whitespace-nowrap rounded-lg px-2.5 py-1.5 transition hover:bg-gray-50"
          >
            <span className={cn('h-2 w-2 rounded-full', s.dot)} />
            <span className="text-sm text-gray-600">{s.label}</span>
            <span className="font-display text-sm font-bold tabular-nums text-gray-900">
              {s.value}
            </span>
          </Link>
        ))}
      </div>
    </Card>
  );
}
