'use client';

import {
  Building2,
  Briefcase,
  Layers,
  Lightbulb,
  MapPin,
  Sparkles,
  Table2,
  Target,
  TrendingUp,
  UserRound,
} from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useActivity } from '@/components/activity-provider';
import { ScorePill } from '@/components/status-badge';
import { buttonClass, Card, EmptyState, ErrorBanner, PageHeader, Spinner } from '@/components/ui';
import { api, type Report, type ReportRow } from '@/lib/api';
import { cn } from '@/lib/utils';

const RANGES = [
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
  { days: 365, label: 'Last 12 months' },
  { days: 0, label: 'All time' },
];

export default function ReportsPage() {
  const { version } = useActivity();
  const [days, setDays] = useState(90);
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .report(days)
      .then((r) => {
        if (!cancelled) {
          setReport(r);
          setError(null);
        }
      })
      .catch(
        (e) => !cancelled && setError(e instanceof Error ? e.message : 'Could not load the report.')
      );
    return () => {
      cancelled = true;
    };
  }, [days, version]);

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="Where you apply, what you target, and how well your resumes fit."
        action={
          <div
            className="no-scrollbar flex max-w-full overflow-x-auto rounded-xl bg-white p-1 shadow-sm ring-1 ring-black/5"
            role="tablist"
            aria-label="Time range"
          >
            {RANGES.map((r) => (
              <button
                key={r.days}
                role="tab"
                aria-selected={days === r.days}
                onClick={() => setDays(r.days)}
                className={cn(
                  'whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition',
                  days === r.days
                    ? 'bg-brand-100 text-brand-900'
                    : 'text-gray-500 hover:text-gray-800'
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        }
      />
      <ErrorBanner message={error} />
      {!report && !error ? (
        <div className="flex justify-center py-24">
          <Spinner />
        </div>
      ) : report && report.totals.tasks === 0 ? (
        <EmptyState
          title="Nothing to report yet"
          body="No tasks in this period. Create tasks and your trends, vendors and positions show up here."
          action={
            days !== 0 ? (
              <button onClick={() => setDays(0)} className={buttonClass('secondary', 'sm')}>
                Show all time
              </button>
            ) : (
              <Link href="/tasks/new" className={buttonClass('primary', 'sm')}>
                New Resume Task
              </Link>
            )
          }
        />
      ) : (
        report && <ReportBody report={report} />
      )}
    </>
  );
}

function ReportBody({ report }: { report: Report }) {
  const t = report.totals;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Kpi
          icon={Layers}
          label="Tasks"
          value={t.tasks}
          note={`${t.vendors} vendor${t.vendors === 1 ? '' : 's'}`}
        />
        <Kpi
          icon={Sparkles}
          label="Tailored"
          value={t.tailored}
          note={`${t.tailored_rate}% of tasks · ${t.ready} waiting`}
        />
        <Kpi
          icon={Target}
          label="Avg match"
          value={t.avg_match !== null ? `${t.avg_match}%` : '—'}
          note="Best resume, before tailoring"
        />
        <Kpi
          icon={TrendingUp}
          label="Avg gain"
          value={t.avg_gain !== null ? `${t.avg_gain > 0 ? '+' : ''}${t.avg_gain} pts` : '—'}
          note={
            t.avg_tailored !== null
              ? `Tailored resumes average ${t.avg_tailored}%`
              : 'Tailor a task to see the gain'
          }
        />
      </div>

      {report.insights.length > 0 && (
        <Card>
          <div className="flex items-center gap-2">
            <Lightbulb className="h-5 w-5 text-accent-500" />
            <h2 className="font-display text-lg font-semibold text-gray-900">What stands out</h2>
          </div>
          <ul className="mt-3 grid gap-2 sm:grid-cols-2">
            {report.insights.map((line) => (
              <li key={line} className="rounded-xl bg-gray-50 px-4 py-3 text-sm text-gray-700">
                {line}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <TrendCard trend={report.trend} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Breakdown
          icon={Building2}
          title="Vendors"
          subtitle="Who you apply through"
          rows={report.vendors}
        />
        <Breakdown
          icon={Briefcase}
          title="Positions"
          subtitle="Similar titles grouped together"
          rows={report.positions}
        />
        <Breakdown
          icon={MapPin}
          title="Locations"
          subtitle="Where the roles are"
          rows={report.locations}
        />
        <Breakdown
          icon={UserRound}
          title="Profiles"
          subtitle="Which of your profiles you use"
          rows={report.profiles}
        />
      </div>
      {report.domains.some((d) => d.name !== 'Not specified') && (
        <Breakdown
          icon={Layers}
          title="Domains"
          subtitle="Industries you apply to"
          rows={report.domains}
        />
      )}
    </div>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  note,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
  note: string;
}) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-gray-500">{label}</p>
        <Icon className="h-5 w-5 text-gray-400" />
      </div>
      <p className="mt-2 font-display text-2xl font-extrabold tabular-nums text-gray-900 sm:text-3xl">
        {value}
      </p>
      <p className="mt-1 text-xs text-gray-500">{note}</p>
    </Card>
  );
}

/*
 * Tasks per week/month as stacked bars of ONE measure split in two, so it uses
 * one hue in two steps (tailored = Underground, not yet = pale silver) rather
 * than two competing colours. Legend + hover tooltip + a table view.
 */
function TrendCard({ trend }: { trend: Report['trend'] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  const points = trend.points;
  const max = Math.max(1, ...points.map((p) => p.total));
  const fmt = (iso: string) =>
    new Date(iso).toLocaleDateString(
      'en-US',
      trend.bucket === 'month'
        ? { month: 'short', year: '2-digit' }
        : { month: 'short', day: 'numeric' }
    );
  const labelEvery = Math.ceil(points.length / 8);

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold text-gray-900">Activity trend</h2>
          <p className="text-sm text-gray-500">Tasks created per {trend.bucket}</p>
        </div>
        <div className="flex items-center gap-4 text-sm text-gray-600">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-brand-500" /> Tailored
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-brand-200" /> Not tailored yet
          </span>
          <button
            onClick={() => setAsTable(!asTable)}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
            aria-pressed={asTable}
          >
            <Table2 className="h-4 w-4" />
            {asTable ? 'Chart' : 'Table'}
          </button>
        </div>
      </div>

      {asTable ? (
        <table className="mt-5 w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="py-2 font-medium">{trend.bucket === 'month' ? 'Month' : 'Week of'}</th>
              <th className="py-2 text-right font-medium">Tasks</th>
              <th className="py-2 text-right font-medium">Tailored</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {points.map((p) => (
              <tr key={p.start}>
                <td className="py-2 text-gray-700">{fmt(p.start)}</td>
                <td className="py-2 text-right tabular-nums text-gray-900">{p.total}</td>
                <td className="py-2 text-right tabular-nums text-gray-900">{p.tailored}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="relative mt-6">
          <div className="pointer-events-none absolute inset-x-0 top-0 border-t border-dashed border-gray-200">
            <span className="absolute -top-2.5 right-0 bg-white pl-2 text-xs tabular-nums text-gray-400">
              {max}
            </span>
          </div>
          <div
            className="flex h-48 items-end gap-1.5 border-b border-gray-200"
            onMouseLeave={() => setHover(null)}
          >
            {points.map((p, i) => {
              const pending = p.total - p.tailored;
              return (
                <div
                  key={p.start}
                  className="relative flex h-full flex-1 flex-col justify-end"
                  onMouseEnter={() => setHover(i)}
                  aria-label={`${fmt(p.start)}: ${p.total} tasks, ${p.tailored} tailored`}
                >
                  {hover === i && (
                    <div className="absolute bottom-full left-1/2 z-10 mb-2 -translate-x-1/2 whitespace-nowrap rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg">
                      <p className="font-semibold">
                        {trend.bucket === 'month' ? fmt(p.start) : `Week of ${fmt(p.start)}`}
                      </p>
                      <p className="mt-0.5 text-gray-300">
                        {p.total} task{p.total === 1 ? '' : 's'} · {p.tailored} tailored
                      </p>
                    </div>
                  )}
                  <div
                    className={cn(
                      'mx-auto flex w-full max-w-10 flex-col gap-0.5',
                      hover === i && 'opacity-90'
                    )}
                  >
                    {pending > 0 && (
                      <div
                        className={cn(
                          'w-full bg-brand-200',
                          p.tailored === 0 ? 'rounded-t' : 'rounded-t'
                        )}
                        style={{ height: `${(pending / max) * 192}px` }}
                      />
                    )}
                    {p.tailored > 0 && (
                      <div
                        className={cn('w-full bg-brand-500', pending === 0 && 'rounded-t')}
                        style={{ height: `${(p.tailored / max) * 192}px` }}
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-2 flex gap-1.5">
            {points.map((p, i) => (
              <span key={p.start} className="flex-1 text-center text-[11px] text-gray-400">
                {i % labelEvery === 0 ? fmt(p.start) : ''}
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function Breakdown({
  icon: Icon,
  title,
  subtitle,
  rows,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  subtitle: string;
  rows: ReportRow[];
}) {
  const max = Math.max(1, ...rows.map((r) => r.tasks));
  return (
    <Card>
      <div className="flex items-center gap-2">
        <Icon className="h-5 w-5 text-gray-400" />
        <h2 className="font-display text-lg font-semibold text-gray-900">{title}</h2>
      </div>
      <p className="text-sm text-gray-500">{subtitle}</p>
      <div className="mt-4 grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-4 gap-y-3 text-sm">
        <span className="text-xs font-medium uppercase tracking-wide text-gray-400">Name</span>
        <span className="text-right text-xs font-medium uppercase tracking-wide text-gray-400">
          Tasks
        </span>
        <span className="text-right text-xs font-medium uppercase tracking-wide text-gray-400">
          Avg match
        </span>
        {rows.map((r) => (
          <Row key={r.name} row={r} max={max} />
        ))}
      </div>
    </Card>
  );
}

function Row({ row, max }: { row: ReportRow; max: number }) {
  const muted = row.name === 'Not specified';
  return (
    <>
      <div className="min-w-0" title={`${row.name}: ${row.tasks} tasks, ${row.tailored} tailored`}>
        <p className={cn('truncate', muted ? 'italic text-gray-400' : 'font-medium text-gray-800')}>
          {row.name}
        </p>
        <div className="mt-1.5 h-1.5 rounded-full bg-gray-100">
          <div
            className={cn('h-full rounded-full', muted ? 'bg-gray-300' : 'bg-brand-400')}
            style={{ width: `${(row.tasks / max) * 100}%` }}
          />
        </div>
      </div>
      <span className="text-right tabular-nums text-gray-900">
        {row.tasks}
        {row.tailored > 0 && (
          <span className="ml-1 text-xs text-gray-400">({row.tailored} tailored)</span>
        )}
      </span>
      <span className="text-right">
        <ScorePill score={row.avg_match} />
      </span>
    </>
  );
}
