'use client';

import { KeyRound } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

/** Shown until an AI provider, model and key are saved on the Settings page. */
export function SetupBanner() {
  const [configured, setConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    api
      .status()
      .then((s) => setConfigured(s.llm_configured))
      .catch(() => setConfigured(null));
  }, []);

  if (configured !== false) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-brand-200 bg-white px-5 py-4">
      <KeyRound className="h-5 w-5 text-accent-500" />
      <p className="flex-1 text-sm text-gray-800">
        <span className="font-semibold">Set up your AI provider first.</span> Choose a provider and
        model and add your API key — matching and tailoring need it.
      </p>
      <Link
        href="/settings"
        className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
      >
        Open Settings
      </Link>
    </div>
  );
}
