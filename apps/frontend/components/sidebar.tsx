'use client';

import {
  BarChart3,
  LayoutDashboard,
  ListChecks,
  Menu,
  Plus,
  Settings,
  UserRound,
  X,
} from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { useActivity } from '@/components/activity-provider';
import { Logo } from '@/components/logo';
import { APP_TAGLINE } from '@/lib/brand';
import { cn } from '@/lib/utils';

const NAV = [
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/tasks', label: 'Tasks', icon: ListChecks },
  { href: '/profiles', label: 'Profiles', icon: UserRound },
  { href: '/reports', label: 'Reports', icon: BarChart3 },
  { href: '/settings', label: 'Settings', icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { dashboard } = useActivity();
  const [open, setOpen] = useState(false);
  const unseen = dashboard?.notifications.filter((t) => t.status !== 'matched').length ?? 0;
  const running = dashboard?.stats.in_progress ?? 0;

  const nav = (
    <nav className="flex flex-col gap-1">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={() => setOpen(false)}
            className={cn(
              'group relative flex items-center gap-3 rounded-xl px-4 py-2.5 text-[15px] font-medium transition-colors',
              active
                ? 'bg-brand-100 text-brand-900'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
            )}
          >
            {active && (
              <span className="absolute inset-y-2 left-0 w-1 rounded-r-full bg-accent-500" />
            )}
            <Icon
              className={cn(
                'h-5 w-5',
                active ? 'text-brand-700' : 'text-gray-400 group-hover:text-gray-600'
              )}
            />
            <span className="flex-1">{label}</span>
            {href === '/tasks' && unseen > 0 && (
              <span className="rounded-full bg-accent-500 px-2 py-0.5 text-xs font-bold text-white">
                {unseen}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );

  const newTask = (
    <Link
      href="/tasks/new"
      onClick={() => setOpen(false)}
      className="flex items-center justify-center gap-2 rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-brand-600"
    >
      <Plus className="h-4 w-4" />
      New Resume Task
    </Link>
  );

  return (
    <>
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 lg:hidden">
        <Link href="/dashboard">
          <Logo />
        </Link>
        <button
          onClick={() => setOpen(!open)}
          aria-label="Menu"
          className="rounded-lg p-2 text-gray-700 hover:bg-gray-100"
        >
          {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>
      {open && (
        <div className="space-y-4 border-b border-gray-200 bg-white p-4 lg:hidden">
          {newTask}
          {nav}
        </div>
      )}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-gray-200 bg-white px-4 py-6 lg:flex">
        <Link href="/dashboard" className="px-2">
          <Logo />
        </Link>
        <p className="mt-2 px-2 text-xs text-gray-500">{APP_TAGLINE}</p>
        <div className="mt-8">{newTask}</div>
        <div className="mt-6 flex-1">{nav}</div>
        {running > 0 && (
          <div className="rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-800 ring-1 ring-brand-100">
            <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-accent-500" />
            {running} task{running === 1 ? '' : 's'} running
          </div>
        )}
      </aside>
    </>
  );
}
