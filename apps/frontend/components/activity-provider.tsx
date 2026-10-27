'use client';

/**
 * Keeps dashboard stats + notifications fresh for the whole app.
 *
 * Polls /dashboard every 4s while any task is running (or right after the
 * user starts one) and every 20s otherwise. Each task that finishes or fails
 * pops a toast once; opening it marks the notification as seen.
 */

import { CheckCircle2, X, XCircle } from 'lucide-react';
import Link from 'next/link';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, type Dashboard, type Task } from '@/lib/api';

interface ActivityContext {
  dashboard: Dashboard | null;
  refresh: () => Promise<void>;
  /** Call after starting a job so polling speeds up immediately. */
  expectActivity: () => void;
  markSeen: (ids?: string[]) => Promise<void>;
  version: number;
}

const Context = createContext<ActivityContext | null>(null);

export function useActivity(): ActivityContext {
  const value = useContext(Context);
  if (!value) throw new Error('useActivity must be used inside ActivityProvider');
  return value;
}

const FAST_MS = 4_000;
const SLOW_MS = 20_000;

export function ActivityProvider({ children }: { children: React.ReactNode }) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [toasts, setToasts] = useState<Task[]>([]);
  const [version, setVersion] = useState(0);
  const announced = useRef<Set<string> | null>(null);
  const fastUntil = useRef(0);
  const dashboardRef = useRef<Dashboard | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.dashboard();
      dashboardRef.current = data;
      setDashboard(data);
      setVersion((v) => v + 1);
      const fresh = data.notifications.filter(
        (t) => t.status === 'finished' || t.status === 'failed'
      );
      if (announced.current === null) {
        // First load: do not toast things that finished while the app was closed.
        announced.current = new Set(fresh.map((t) => `${t.task_id}:${t.updated_at}`));
        return;
      }
      const newOnes = fresh.filter((t) => !announced.current!.has(`${t.task_id}:${t.updated_at}`));
      newOnes.forEach((t) => announced.current!.add(`${t.task_id}:${t.updated_at}`));
      if (newOnes.length) setToasts((current) => [...newOnes, ...current].slice(0, 4));
    } catch {
      /* backend restarting; try again next tick */
    }
  }, []);

  const expectActivity = useCallback(() => {
    fastUntil.current = Date.now() + 15_000;
  }, []);

  const markSeen = useCallback(
    async (ids?: string[]) => {
      await api.markSeen(ids).catch(() => undefined);
      setToasts((current) => (ids ? current.filter((t) => !ids.includes(t.task_id)) : []));
      await refresh();
    },
    [refresh]
  );

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const tick = async () => {
      await refresh();
      if (stopped) return;
      const busy =
        (dashboardRef.current?.stats.in_progress ?? 0) > 0 || Date.now() < fastUntil.current;
      timer = setTimeout(tick, busy ? FAST_MS : SLOW_MS);
    };
    tick();
    const onFocus = () => refresh();
    window.addEventListener('focus', onFocus);
    return () => {
      stopped = true;
      clearTimeout(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [refresh]);

  return (
    <Context.Provider value={{ dashboard, refresh, expectActivity, markSeen, version }}>
      {children}
      <div className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col gap-3 sm:inset-x-auto sm:bottom-6 sm:right-6 sm:w-[22rem]">
        {toasts.map((task) => (
          <Toast
            key={`${task.task_id}:${task.updated_at}`}
            task={task}
            onOpen={() => markSeen([task.task_id])}
            onClose={() => setToasts((current) => current.filter((t) => t !== task))}
          />
        ))}
      </div>
    </Context.Provider>
  );
}

function Toast({ task, onOpen, onClose }: { task: Task; onOpen: () => void; onClose: () => void }) {
  const ok = task.status === 'finished';
  useEffect(() => {
    const timer = setTimeout(onClose, 12_000);
    return () => clearTimeout(timer);
  }, [onClose]);
  return (
    <div className="animate-toast-in pointer-events-auto flex gap-3 rounded-xl bg-white p-4 shadow-lg ring-1 ring-gray-200">
      {ok ? (
        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-brand-500" />
      ) : (
        <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-gray-900">
          {ok ? 'Resume tailored' : 'Task failed'}
        </p>
        <p className="truncate text-sm text-gray-600">
          {task.job_title}
          {task.vendor_company ? ` · ${task.vendor_company}` : ''}
        </p>
        <Link
          href={`/tasks/${task.task_id}`}
          onClick={onOpen}
          className="mt-1 inline-block text-sm font-semibold text-brand-800 underline-offset-4 hover:text-accent-600 hover:underline"
        >
          {ok ? 'Open and download' : 'See what went wrong'}
        </Link>
      </div>
      <button
        onClick={onClose}
        className="self-start text-gray-400 hover:text-gray-600"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
