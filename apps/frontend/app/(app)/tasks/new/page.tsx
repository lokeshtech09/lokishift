'use client';

import { FileText } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { useActivity } from '@/components/activity-provider';
import { SetupBanner } from '@/components/setup-banner';
import {
  Button,
  buttonClass,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  inputClass,
  Spinner,
} from '@/components/ui';
import { api, type Connection, DOMAINS, type Profile, type TaskInput } from '@/lib/api';
import { cn } from '@/lib/utils';

const LAST_PROFILE_KEY = 'lokishift:last-profile';

const EMPTY: TaskInput = {
  profile_id: '',
  job_title: '',
  job_location: '',
  vendor_company: '',
  domain: '',
  job_description: '',
  recruiter_name: '',
  recruiter_email: '',
  vendor_name: '',
  vendor_email: '',
  ai_instructions: '',
  auto_tailor: false,
  connection_id: null,
};

export default function NewTaskPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <NewTaskForm />
    </Suspense>
  );
}

function NewTaskForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { expectActivity, refresh } = useActivity();
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [form, setForm] = useState<TaskInput>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listConnections()
      .then(setConnections)
      .catch(() => setConnections([]));
  }, []);

  useEffect(() => {
    api
      .listProfiles()
      .then((list) => {
        setProfiles(list);
        let stored: string | null = null;
        try {
          stored = localStorage.getItem(LAST_PROFILE_KEY);
        } catch {
          /* storage unavailable */
        }
        const wanted = params.get('profile') || stored;
        const usable = list.filter((p) => (p.resume_count ?? 0) > 0);
        const pick = usable.find((p) => p.profile_id === wanted) ?? usable[0];
        if (pick) setForm((f) => ({ ...f, profile_id: pick.profile_id }));
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load profiles.'));
  }, [params]);

  const set = <K extends keyof TaskInput>(key: K, value: TaskInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const selected = profiles?.find((p) => p.profile_id === form.profile_id);
  const jdShort = form.job_description.trim().length > 0 && form.job_description.trim().length < 50;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const task = await api.createTask(form);
      try {
        localStorage.setItem(LAST_PROFILE_KEY, form.profile_id);
      } catch {
        /* storage unavailable */
      }
      expectActivity();
      refresh();
      router.push(`/tasks/${task.task_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the task.');
      setSaving(false);
    }
  };

  if (profiles === null && !error) {
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  }
  if (profiles && !profiles.some((p) => (p.resume_count ?? 0) > 0)) {
    return (
      <EmptyState
        title="Upload a resume first"
        body="Tasks match a job description against the resumes in a profile. Create a profile and upload at least one .docx resume."
        action={
          <Link href="/profiles" className={buttonClass('primary')}>
            Go to profiles
          </Link>
        }
      />
    );
  }

  return (
    <>
      <SetupBanner />
      <Card className="mx-auto max-w-4xl p-8 sm:p-10">
        <h1 className="font-display text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
          Create New Resume Task
        </h1>
        <p className="mt-2 text-gray-500">
          Provide job details and LokiShift will pick your best resume and tailor it.
        </p>

        <form onSubmit={submit} className="mt-8 space-y-10">
          <Section title="Profile">
            <Field label="Apply with profile" required>
              <select
                required
                value={form.profile_id}
                onChange={(e) => set('profile_id', e.target.value)}
                className={inputClass}
              >
                <option value="" disabled>
                  Select a profile
                </option>
                {profiles?.map((p) => (
                  <option
                    key={p.profile_id}
                    value={p.profile_id}
                    disabled={(p.resume_count ?? 0) === 0}
                  >
                    {p.title}
                    {p.full_name ? ` — ${p.full_name}` : ''} ({p.resume_count ?? 0} resume
                    {p.resume_count === 1 ? '' : 's'})
                  </option>
                ))}
              </select>
            </Field>
            {selected && (
              <p className="flex items-center gap-2 text-sm text-gray-500">
                <FileText className="h-4 w-4" />
                All {selected.resume_count} resume{selected.resume_count === 1 ? '' : 's'} in this
                profile are scored against the JD; the best one is picked for tailoring.
              </p>
            )}
          </Section>

          <Section title="Job Information">
            <Field label="Job Title" required>
              <input
                required
                value={form.job_title}
                onChange={(e) => set('job_title', e.target.value)}
                placeholder="Senior Python Developer"
                className={inputClass}
              />
            </Field>
            <Field label="Job Location" required>
              <input
                required
                value={form.job_location}
                onChange={(e) => set('job_location', e.target.value)}
                placeholder="New York, NY"
                className={inputClass}
              />
            </Field>
            <Field label="Vendor Company" required>
              <input
                required
                value={form.vendor_company}
                onChange={(e) => set('vendor_company', e.target.value)}
                placeholder="ABC Staffing"
                className={inputClass}
              />
            </Field>
            <Field label="Domain">
              <select
                value={form.domain}
                onChange={(e) => set('domain', e.target.value)}
                className={inputClass}
              >
                <option value="">Select Domain</option>
                {DOMAINS.map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </Field>
            <Field
              label="Job Description"
              required
              error={
                jdShort ? 'Paste the full job description (at least 50 characters).' : undefined
              }
            >
              <textarea
                required
                minLength={50}
                rows={12}
                value={form.job_description}
                onChange={(e) => set('job_description', e.target.value)}
                placeholder="Paste the job description here..."
                className={cn(inputClass, 'font-mono text-sm leading-relaxed')}
              />
            </Field>
          </Section>

          <Section title="Optional Details">
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Recruiter Name">
                <input
                  value={form.recruiter_name}
                  onChange={(e) => set('recruiter_name', e.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="Recruiter Email">
                <input
                  type="email"
                  value={form.recruiter_email}
                  onChange={(e) => set('recruiter_email', e.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="Vendor Name">
                <input
                  value={form.vendor_name}
                  onChange={(e) => set('vendor_name', e.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="Vendor Email" hint="Used by the Mail Vendor button.">
                <input
                  type="email"
                  value={form.vendor_email}
                  onChange={(e) => set('vendor_email', e.target.value)}
                  className={inputClass}
                />
              </Field>
            </div>
            {connections.length > 1 && (
              <Field
                label="AI connection"
                hint="Leave on default unless you want this one task to use a different AI. Backups still apply if it fails."
              >
                <select
                  value={form.connection_id ?? ''}
                  onChange={(e) => set('connection_id', e.target.value || null)}
                  className={inputClass}
                >
                  {connections.map((c) =>
                    c.is_default ? (
                      <option key={c.connection_id} value="">
                        Default — {c.name} ({c.model})
                      </option>
                    ) : (
                      <option key={c.connection_id} value={c.connection_id}>
                        {c.name} ({c.model})
                      </option>
                    )
                  )}
                </select>
              </Field>
            )}
            <Field label="AI Instructions">
              <textarea
                rows={3}
                value={form.ai_instructions}
                onChange={(e) => set('ai_instructions', e.target.value)}
                placeholder="Any special instructions for the AI? e.g. emphasise Azure, keep it to 2 pages"
                className={cn(inputClass, 'font-mono text-sm')}
              />
            </Field>
          </Section>

          <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-gray-200 bg-gray-50 p-4">
            <input
              type="checkbox"
              checked={form.auto_tailor}
              onChange={(e) => set('auto_tailor', e.target.checked)}
              className="mt-1 h-4 w-4 accent-brand-600"
            />
            <span>
              <span className="block font-semibold text-gray-900">Tailor automatically</span>
              <span className="text-sm text-gray-600">
                Skip the review step: tailor the best match as soon as matching finishes.
                You&apos;ll be notified when it&apos;s ready.
              </span>
            </span>
          </label>

          <ErrorBanner message={error} />
          <Button type="submit" loading={saving} className="w-full py-3.5 text-base">
            {form.auto_tailor ? 'Create & Tailor' : 'Create Task & Match Resumes'}
          </Button>
        </form>
      </Card>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-5">
      <h2 className="font-display text-xl font-semibold text-gray-900">{title}</h2>
      {children}
    </section>
  );
}
