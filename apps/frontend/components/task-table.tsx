'use client';

import { ChevronRight, Download, Mail, Wand2 } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';
import { useActivity } from '@/components/activity-provider';
import { ScorePill, StatusBadge } from '@/components/status-badge';
import { api, formatDate, mailVendorHref, type Task } from '@/lib/api';
import { cn } from '@/lib/utils';

/**
 * Task list: a table on wide screens, stacked cards on phones. Both views
 * share the same actions (tailor, download, mail vendor, "new" marker).
 */
export function TaskTable({
  tasks,
  candidates,
  onChanged,
  showProfile = true,
}: {
  tasks: Task[];
  /** profile_id -> candidate full name, for the mail draft signature. */
  candidates: Record<string, string>;
  onChanged?: () => void;
  showProfile?: boolean;
}) {
  return (
    <>
      <ul className="divide-y divide-gray-100 md:hidden">
        {tasks.map((task) => (
          <TaskCard
            key={task.task_id}
            task={task}
            candidate={candidates[task.profile_id] ?? ''}
            onChanged={onChanged}
            showProfile={showProfile}
          />
        ))}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[820px] text-left">
          <thead>
            <tr className="bg-gray-50 text-sm font-semibold text-gray-600">
              <th className="rounded-l-lg px-4 py-3.5">Job Title</th>
              <th className="px-4 py-3.5">Vendor Company</th>
              <th className="px-4 py-3.5">Match</th>
              <th className="px-4 py-3.5">Status</th>
              <th className="px-4 py-3.5">Created</th>
              <th className="px-4 py-3.5">Download</th>
              <th className="rounded-r-lg px-4 py-3.5">Mail Vendor</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {tasks.map((task) => (
              <TaskRow
                key={task.task_id}
                task={task}
                candidate={candidates[task.profile_id] ?? ''}
                onChanged={onChanged}
                showProfile={showProfile}
              />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function useTaskActions(task: Task, candidate: string, onChanged?: () => void) {
  const { expectActivity, markSeen } = useActivity();
  const [busy, setBusy] = useState(false);
  const mail = task.status === 'finished' ? mailVendorHref(task, candidate) : null;
  const unseen = !task.seen && (task.status === 'finished' || task.status === 'failed');

  const tailor = async () => {
    setBusy(true);
    try {
      await api.tailorTask(task.task_id);
      expectActivity();
      onChanged?.();
    } finally {
      setBusy(false);
    }
  };
  const open = () => {
    if (unseen) markSeen([task.task_id]);
  };
  return { busy, tailor, mail, unseen, open };
}

const pillButton =
  'inline-flex items-center justify-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-800 hover:bg-gray-50';
const solidButton =
  'inline-flex items-center justify-center gap-1.5 rounded-lg bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-60';

function Scores({ task }: { task: Task }) {
  return (
    <div className="flex items-center gap-1.5">
      <ScorePill score={task.match_score} muted={task.tailored_score !== null} />
      {task.tailored_score !== null && (
        <>
          <span className="text-gray-400">→</span>
          <ScorePill score={task.tailored_score} />
        </>
      )}
    </div>
  );
}

function MainAction({ task, busy, tailor }: { task: Task; busy: boolean; tailor: () => void }) {
  if (task.status === 'finished' && task.has_tailored_docx) {
    return (
      <a href={api.taskDownloadUrl(task.task_id)} className={pillButton}>
        <Download className="h-4 w-4" />
        Download
      </a>
    );
  }
  if (task.status === 'matched') {
    return (
      <button onClick={tailor} disabled={busy} className={solidButton}>
        <Wand2 className="h-4 w-4" />
        Tailor
      </button>
    );
  }
  return null;
}

function MailAction({ task, mail }: { task: Task; mail: string | null }) {
  if (mail) {
    return (
      <a href={mail} className={pillButton}>
        <Mail className="h-4 w-4" />
        Mail
      </a>
    );
  }
  return (
    <span
      className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-300"
      title={
        task.status !== 'finished'
          ? 'Available once the resume is tailored'
          : 'Add a vendor or recruiter email to the task'
      }
    >
      <Mail className="h-4 w-4" />
      Mail
    </span>
  );
}

function TaskCard({
  task,
  candidate,
  onChanged,
  showProfile,
}: {
  task: Task;
  candidate: string;
  onChanged?: () => void;
  showProfile: boolean;
}) {
  const { busy, tailor, mail, unseen, open } = useTaskActions(task, candidate, onChanged);
  return (
    <li className={cn('py-4', unseen && '-mx-3 rounded-xl bg-brand-50/60 px-3')}>
      <Link href={`/tasks/${task.task_id}`} onClick={open} className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-gray-900">
            {task.job_title}
            {unseen && (
              <span className="ml-2 inline-block h-2 w-2 rounded-full bg-accent-500 align-middle" />
            )}
          </p>
          <p className="mt-0.5 truncate text-sm text-gray-500">
            {[
              task.vendor_company,
              showProfile ? task.profile_title : null,
              formatDate(task.created_at),
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
        <ChevronRight className="mt-1 h-5 w-5 shrink-0 text-gray-300" />
      </Link>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <StatusBadge status={task.status} />
        <Scores task={task} />
        <div className="ml-auto flex gap-2">
          <MainAction task={task} busy={busy} tailor={tailor} />
          {task.status === 'finished' && mail && <MailAction task={task} mail={mail} />}
        </div>
      </div>
    </li>
  );
}

function TaskRow({
  task,
  candidate,
  onChanged,
  showProfile,
}: {
  task: Task;
  candidate: string;
  onChanged?: () => void;
  showProfile: boolean;
}) {
  const { busy, tailor, mail, unseen, open } = useTaskActions(task, candidate, onChanged);
  return (
    <tr className={cn('align-middle', unseen && 'bg-brand-50/40')}>
      <td className="px-4 py-4">
        <Link
          href={`/tasks/${task.task_id}`}
          onClick={open}
          className="font-semibold text-brand-800 underline-offset-4 hover:text-accent-600 hover:underline"
        >
          {task.job_title}
        </Link>
        {unseen && (
          <span
            className="ml-2 inline-block h-2 w-2 rounded-full bg-accent-500 align-middle"
            title="New"
          />
        )}
        {showProfile && <p className="mt-0.5 text-xs text-gray-500">{task.profile_title}</p>}
      </td>
      <td className="px-4 py-4 text-gray-800">
        {task.vendor_company || <span className="text-gray-400">—</span>}
      </td>
      <td className="px-4 py-4">
        <Scores task={task} />
      </td>
      <td className="px-4 py-4">
        <StatusBadge status={task.status} />
      </td>
      <td className="whitespace-nowrap px-4 py-4 text-gray-700">{formatDate(task.created_at)}</td>
      <td className="px-4 py-4">
        {task.status === 'finished' || task.status === 'matched' ? (
          <MainAction task={task} busy={busy} tailor={tailor} />
        ) : (
          <span className="text-sm text-gray-400">—</span>
        )}
      </td>
      <td className="px-4 py-4">
        <MailAction task={task} mail={mail} />
      </td>
    </tr>
  );
}
