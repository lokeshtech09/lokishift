'use client';

import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  Download,
  Mail,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Trophy,
  Wand2,
} from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { useActivity } from '@/components/activity-provider';
import { ScorePill, StatusBadge } from '@/components/status-badge';
import { Button, Card, ErrorBanner, Spinner } from '@/components/ui';
import { api, formatDate, mailVendorHref, type Ranking, type Task, timeAgo } from '@/lib/api';
import { cn } from '@/lib/utils';

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { version, expectActivity, markSeen, refresh } = useActivity();
  const [task, setTask] = useState<Task | null>(null);
  const [candidate, setCandidate] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const t = await api.getTask(id);
      setTask(t);
      setError(null);
      if (!t.seen) markSeen([t.task_id]);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the task.');
    }
  }, [id, markSeen]);

  useEffect(() => {
    load();
  }, [load, version]);

  // Poll faster than the global ticker while this task runs.
  const running = task?.status === 'matching' || task?.status === 'tailoring';
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [running, load]);

  useEffect(() => {
    if (!task) return;
    api
      .getProfile(task.profile_id)
      .then((p) => setCandidate(p.full_name))
      .catch(() => undefined);
  }, [task?.profile_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (name: string, fn: () => Promise<Task | unknown>) => {
    setBusy(name);
    setActionError(null);
    try {
      const result = await fn();
      if (result && typeof result === 'object' && 'task_id' in result) setTask(result as Task);
      expectActivity();
      refresh();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Something went wrong.');
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorBanner message={error} />;
  if (!task)
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );

  const rankings = task.ranking?.rankings ?? [];
  const best = rankings.find((r) => r.resume_id === task.best_resume_id);
  const mail = mailVendorHref(task, candidate);

  return (
    <>
      <Link
        href="/tasks"
        className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" />
        All tasks
      </Link>

      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-display text-3xl font-bold tracking-tight text-gray-900">
              {task.job_title}
            </h1>
            <StatusBadge status={task.status} />
          </div>
          <p className="mt-2 text-gray-600">
            {[task.vendor_company, task.job_location, task.domain].filter(Boolean).join(' · ')}
          </p>
          <p className="mt-1 text-sm text-gray-500">
            Profile:{' '}
            <Link
              href={`/profiles/${task.profile_id}`}
              className="font-semibold text-brand-800 underline-offset-4 hover:text-accent-600 hover:underline"
            >
              {task.profile_title}
            </Link>{' '}
            · Created {formatDate(task.created_at)}
          </p>
          {task.llm_used && (
            <p className="mt-1 text-sm text-gray-500">
              AI: <span className="font-medium text-gray-700">{task.llm_used}</span>
              {(task.tailoring?.backup_used || task.ranking?.backup_used) && (
                <span
                  className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600"
                  title={(
                    task.tailoring?.failed_connections ??
                    task.ranking?.failed_connections ??
                    []
                  ).join('\n')}
                >
                  backup used
                </span>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {task.status === 'finished' && (
            <>
              <a
                href={api.taskDownloadUrl(task.task_id)}
                className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700"
              >
                <Download className="h-4 w-4" />
                Download .docx
              </a>
              {mail ? (
                <a
                  href={mail}
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-800 hover:bg-gray-50"
                >
                  <Mail className="h-4 w-4" />
                  Mail Vendor
                </a>
              ) : null}
            </>
          )}
          <Button
            variant="danger"
            loading={busy === 'delete'}
            onClick={() => {
              if (!confirm('Delete this task?')) return;
              act('delete', async () => {
                await api.deleteTask(task.task_id);
                router.push('/tasks');
              });
            }}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="space-y-6">
        <ErrorBanner message={actionError} />

        {task.status === 'matching' && (
          <Progress
            title="Matching your resumes"
            body={`Scoring every resume in “${task.profile_title}” against this job description.${task.auto_tailor ? ' Tailoring starts automatically afterwards.' : ''}`}
          />
        )}
        {task.status === 'tailoring' && (
          <Progress
            title="Tailoring in the background"
            body={`Rewriting ${rankings.find((r) => r.resume_id === task.tailored_resume_id)?.name ?? 'your resume'} for this role. This usually takes 1–3 minutes — you can leave this page; you'll get a notification when it's done.`}
          />
        )}
        {task.status === 'failed' && (
          <Card className="border-l-4 border-red-500">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
              <div className="flex-1">
                <p className="font-semibold text-gray-900">This task failed</p>
                <p className="mt-1 text-gray-700">{task.error}</p>
                <p className="mt-1 text-xs text-gray-500">
                  {task.finished_at && timeAgo(task.finished_at)}
                </p>
              </div>
              <Button
                loading={busy === 'retry'}
                onClick={() => act('retry', () => api.retryTask(task.task_id))}
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </Button>
            </div>
          </Card>
        )}

        {task.status === 'finished' && task.tailoring && <TailoringResult task={task} />}

        {rankings.length > 0 && (
          <Card>
            <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 className="font-display text-lg font-semibold text-gray-900">Resume match</h2>
                <p className="text-sm text-gray-500">
                  {rankings.length} resume{rankings.length === 1 ? '' : 's'} scored against this
                  job.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={running}
                  loading={busy === 'rematch'}
                  onClick={() => act('rematch', () => api.rematchTask(task.task_id))}
                >
                  <RefreshCw className="h-4 w-4" />
                  Re-score
                </Button>
                {(task.status === 'matched' ||
                  task.status === 'finished' ||
                  task.status === 'failed') &&
                  best && (
                    <Button
                      loading={busy === 'tailor'}
                      onClick={() => act('tailor', () => api.tailorTask(task.task_id))}
                    >
                      <Wand2 className="h-4 w-4" />
                      {task.status === 'finished' ? 'Tailor again' : 'Tailor resume'}
                    </Button>
                  )}
              </div>
            </div>
            {task.ranking?.warning && (
              <p className="mb-4 rounded-lg bg-gray-50 px-4 py-2.5 text-sm text-gray-700">
                {task.ranking.warning}
              </p>
            )}
            <div className="space-y-3">
              {rankings.map((r, i) => (
                <RankingRow
                  key={r.resume_id}
                  ranking={r}
                  best={i === 0 || r.resume_id === task.best_resume_id}
                  canTailor={!running && r.resume_id !== task.best_resume_id}
                  loading={busy === `tailor-${r.resume_id}`}
                  onTailor={() =>
                    act(`tailor-${r.resume_id}`, () =>
                      api.tailorTask(task.task_id, { resume_id: r.resume_id })
                    )
                  }
                />
              ))}
            </div>
          </Card>
        )}

        <JobDetails task={task} />
      </div>
    </>
  );
}

function Progress({ title, body }: { title: string; body: string }) {
  return (
    <Card className="flex items-center gap-5">
      <div className="relative flex h-12 w-12 shrink-0 items-center justify-center">
        <span className="absolute inset-0 animate-ping rounded-full bg-brand-100" />
        <Sparkles className="relative h-6 w-6 text-brand-600" />
      </div>
      <div>
        <p className="font-semibold text-gray-900">{title}</p>
        <p className="mt-0.5 text-sm text-gray-600">{body}</p>
      </div>
    </Card>
  );
}

function RankingRow({
  ranking,
  best,
  canTailor,
  loading,
  onTailor,
}: {
  ranking: Ranking;
  best: boolean;
  canTailor: boolean;
  loading: boolean;
  onTailor: () => void;
}) {
  const [open, setOpen] = useState(best);
  return (
    <div
      className={cn(
        'rounded-xl border p-4',
        best ? 'border-brand-500 bg-brand-50/40' : 'border-gray-200'
      )}
    >
      {/* Line 1: name + score. Line 2 (wraps on phones): bar, badge, action. */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setOpen(!open)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 text-gray-400 transition-transform',
              !open && '-rotate-90'
            )}
          />
          {best && <Trophy className="h-4 w-4 shrink-0 text-brand-600" />}
          <span className="min-w-0 truncate font-medium text-gray-900">{ranking.name}</span>
        </button>
        <ScorePill score={ranking.score} />
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-3 pl-6">
        <div className="h-2 min-w-[8rem] flex-1 overflow-hidden rounded-full bg-gray-200 sm:max-w-xs">
          <div
            className={cn(
              'h-full rounded-full',
              ranking.score >= 80
                ? 'bg-brand-500'
                : ranking.score >= 60
                  ? 'bg-gray-400'
                  : 'bg-red-500'
            )}
            style={{ width: `${ranking.score}%` }}
          />
        </div>
        {best && (
          <span className="rounded-full bg-brand-600 px-2 py-0.5 text-xs font-semibold text-white">
            Best match
          </span>
        )}
        {canTailor && (
          <Button
            variant="secondary"
            size="sm"
            loading={loading}
            onClick={onTailor}
            className="ml-auto"
          >
            Tailor this one
          </Button>
        )}
      </div>
      {open && (
        <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2 sm:pl-6">
          {ranking.reasoning && <p className="text-gray-700 sm:col-span-2">{ranking.reasoning}</p>}
          <TagList
            title="Matches"
            items={
              ranking.strengths.length ? ranking.strengths : ranking.matched_keywords.slice(0, 10)
            }
            tone="green"
          />
          <TagList
            title="Gaps (tailoring will cover these)"
            items={ranking.gaps.length ? ranking.gaps : ranking.missing_keywords.slice(0, 10)}
            tone="amber"
          />
        </div>
      )}
    </div>
  );
}

function TagList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: 'green' | 'amber';
}) {
  if (!items.length) return null;
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500">{title}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={item}
            className={cn(
              'rounded-md px-2 py-0.5 text-xs',
              tone === 'green' ? 'bg-brand-50 text-brand-800' : 'bg-gray-100 text-gray-700'
            )}
          >
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function TailoringResult({ task }: { task: Task }) {
  const report = task.tailoring!;
  const [showAll, setShowAll] = useState(false);
  const fromJd = [
    ...report.additions.map((a) => ({ kind: 'New bullet', text: a.text, detail: a.keywords })),
    ...report.edits
      .filter((e) => e.added_from_jd.length)
      .map((e) => ({ kind: 'Rewritten', text: e.new_text, detail: e.added_from_jd })),
  ];
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-6">
        <div>
          <p className="text-sm font-medium text-gray-500">Match score</p>
          <div className="mt-1 flex items-center gap-3 text-3xl font-bold tabular-nums">
            <span className="text-gray-400">{report.score_before ?? '–'}%</span>
            <span className="text-gray-300">→</span>
            <span className="text-brand-600">{report.score_after}%</span>
          </div>
        </div>
        <div className="h-12 w-px bg-gray-200" />
        <Stat label="Lines rewritten" value={report.edits.length} />
        <Stat label="Bullets added" value={report.additions.length} />
        <Stat
          label="Keyword coverage"
          value={`${report.keyword_score_before}% → ${report.keyword_score_after}%`}
        />
      </div>
      <p className="mt-5 text-gray-700">{report.summary}</p>
      <p className="mt-1 text-xs text-gray-500">
        Based on “{report.resume_name}” · saved as {task.tailored_filename}
      </p>

      {fromJd.length > 0 && (
        <div className="mt-6 rounded-xl bg-accent-50 p-5">
          <div className="flex items-center gap-2">
            <Plus className="h-4 w-4 text-accent-700" />
            <p className="font-semibold text-accent-900">
              Added from the job description — be ready to talk about these
            </p>
          </div>
          <ul className="mt-3 space-y-2.5">
            {fromJd.map((item, i) => (
              <li key={i} className="text-sm text-gray-800">
                <span className="mr-2 rounded bg-white px-1.5 py-0.5 text-xs font-semibold text-accent-800">
                  {item.kind}
                </span>
                {item.text}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.missing_after.length > 0 && (
        <p className="mt-4 text-sm text-gray-600">
          <span className="font-medium">Still not mentioned:</span>{' '}
          {report.missing_after.slice(0, 12).join(', ')}
        </p>
      )}

      <button
        onClick={() => setShowAll(!showAll)}
        className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-brand-800 underline-offset-4 hover:text-accent-600 hover:underline"
      >
        <ChevronDown className={cn('h-4 w-4 transition-transform', !showAll && '-rotate-90')} />
        {showAll ? 'Hide' : 'Show'} all {report.edits.length + report.additions.length} changes
      </button>
      {showAll && (
        <div className="mt-4 space-y-3">
          {report.edits.map((e) => (
            <div key={e.index} className="rounded-lg border border-gray-200 p-4 text-sm">
              <p className="text-gray-500 line-through decoration-gray-300">{e.original_text}</p>
              <p className="mt-2 text-gray-900">{e.new_text}</p>
            </div>
          ))}
          {report.additions.map((a, i) => (
            <div
              key={`a${i}`}
              className="rounded-lg border border-brand-200 bg-brand-50/50 p-4 text-sm"
            >
              <p className="text-xs text-gray-500">
                New bullet after: “{a.anchor_text.slice(0, 90)}
                {a.anchor_text.length > 90 ? '…' : ''}”
              </p>
              <p className="mt-1.5 text-gray-900">{a.text}</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-sm font-medium text-gray-500">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-gray-900">{value}</p>
    </div>
  );
}

function JobDetails({ task }: { task: Task }) {
  const [open, setOpen] = useState(false);
  const contacts = [
    ['Recruiter', task.recruiter_name, task.recruiter_email],
    ['Vendor', task.vendor_name, task.vendor_email],
  ].filter(([, name, email]) => name || email);
  return (
    <Card>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-left"
      >
        <h2 className="font-display text-lg font-semibold text-gray-900">Job details</h2>
        <ChevronDown
          className={cn('h-5 w-5 text-gray-400 transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <div className="mt-5 space-y-5 text-sm">
          {contacts.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2">
              {contacts.map(([role, name, email]) => (
                <div key={role} className="rounded-lg bg-gray-50 p-3">
                  <p className="text-xs font-semibold uppercase text-gray-500">{role}</p>
                  <p className="text-gray-900">{name}</p>
                  {email && <p className="text-gray-600">{email}</p>}
                </div>
              ))}
            </div>
          )}
          {task.ai_instructions && (
            <div>
              <p className="mb-1 text-xs font-semibold uppercase text-gray-500">AI instructions</p>
              <p className="text-gray-800">{task.ai_instructions}</p>
            </div>
          )}
          <div>
            <p className="mb-1 text-xs font-semibold uppercase text-gray-500">Job description</p>
            <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-lg bg-gray-50 p-4 font-sans text-gray-800">
              {task.job_description}
            </pre>
          </div>
        </div>
      )}
    </Card>
  );
}
