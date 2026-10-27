'use client';

import { CheckCheck, Search } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useCallback, useEffect, useState } from 'react';
import { useActivity } from '@/components/activity-provider';
import { TaskTable } from '@/components/task-table';
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  inputClass,
  PageHeader,
  Spinner,
} from '@/components/ui';
import { api, type Profile, type Task } from '@/lib/api';
import { cn } from '@/lib/utils';

const FILTERS = [
  { value: '', label: 'All' },
  { value: 'matched', label: 'Ready to tailor' },
  { value: 'running', label: 'Running' },
  { value: 'finished', label: 'Finished' },
  { value: 'failed', label: 'Failed' },
];

export default function TasksPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <TasksView />
    </Suspense>
  );
}

function TasksView() {
  const router = useRouter();
  const params = useSearchParams();
  const status = params.get('status') ?? '';
  const profileId = params.get('profile') ?? '';
  const { version, dashboard, markSeen, refresh } = useActivity();
  const [query, setQuery] = useState('');
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [error, setError] = useState<string | null>(null);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`/tasks${next.toString() ? `?${next}` : ''}`);
  };

  const load = useCallback(async () => {
    try {
      const filter = status === 'running' ? undefined : status || undefined;
      const [list, profs] = await Promise.all([
        api.listTasks({
          status: filter,
          profile_id: profileId || undefined,
          q: query.trim() || undefined,
          limit: 300,
        }),
        api.listProfiles(),
      ]);
      setTasks(
        status === 'running'
          ? list.filter((t) => t.status === 'matching' || t.status === 'tailoring')
          : list
      );
      setProfiles(profs);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load tasks.');
    }
  }, [status, profileId, query]);

  useEffect(() => {
    const timer = setTimeout(load, query ? 250 : 0);
    return () => clearTimeout(timer);
  }, [load, version, query]);

  const unseen = dashboard?.notifications.length ?? 0;
  const candidates = Object.fromEntries(profiles.map((p) => [p.profile_id, p.full_name]));

  return (
    <>
      <PageHeader title="Tasks" subtitle="Every job you've matched and tailored a resume for." />
      <Card>
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <div className="no-scrollbar flex max-w-full gap-1 overflow-x-auto rounded-xl bg-gray-100 p-1">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setParam('status', f.value)}
                className={cn(
                  'whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium',
                  status === f.value
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <select
            value={profileId}
            onChange={(e) => setParam('profile', e.target.value)}
            className={cn(inputClass, 'w-auto py-2 text-sm')}
          >
            <option value="">All profiles</option>
            {profiles.map((p) => (
              <option key={p.profile_id} value={p.profile_id}>
                {p.title}
              </option>
            ))}
          </select>
          <div className="relative min-w-[14rem] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search job title or vendor"
              className={cn(inputClass, 'py-2 pl-9 text-sm')}
            />
          </div>
          {unseen > 0 && (
            <Button variant="ghost" size="sm" onClick={() => markSeen().then(refresh)}>
              <CheckCheck className="h-4 w-4" />
              Mark all seen
            </Button>
          )}
        </div>
        <ErrorBanner message={error} />
        {tasks === null && !error ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : tasks && tasks.length === 0 ? (
          <EmptyState
            title="No tasks here"
            body="Try another filter, or create a new resume task."
          />
        ) : (
          tasks && <TaskTable tasks={tasks} candidates={candidates} onChanged={load} />
        )}
      </Card>
    </>
  );
}
