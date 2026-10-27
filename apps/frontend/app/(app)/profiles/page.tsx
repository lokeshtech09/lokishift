'use client';

import { FileText, ListChecks, Plus, UserRound } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  EmptyState,
  ErrorBanner,
  Field,
  inputClass,
  PageHeader,
  Spinner,
} from '@/components/ui';
import { api, type Profile } from '@/lib/api';

export default function ProfilesPage() {
  const router = useRouter();
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [fullName, setFullName] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listProfiles()
      .then((list) => {
        setProfiles(list);
        if (list.length === 0) setCreating(true);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load profiles.'));
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      // New profiles reuse the candidate details of an existing one.
      const source = profiles?.find((p) => p.full_name);
      const profile = await api.createProfile({
        title: title.trim(),
        full_name: fullName.trim() || source?.full_name || '',
        email: source?.email ?? '',
        phone: source?.phone ?? '',
        linkedin: source?.linkedin ?? '',
        location: source?.location ?? '',
        total_experience: source?.total_experience ?? '',
        experience: source?.experience ?? [],
      });
      router.push(`/profiles/${profile.profile_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the profile.');
      setSaving(false);
    }
  };

  const knownName = profiles?.find((p) => p.full_name)?.full_name;

  return (
    <>
      <PageHeader
        title="Profiles"
        subtitle="One profile per job title you apply for. Each holds as many resume versions as you like."
        action={
          !creating && (
            <Button onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" />
              New Profile
            </Button>
          )
        }
      />
      <ErrorBanner message={error} />

      {creating && (
        <Card className="mb-8">
          <form onSubmit={create} className="grid gap-5 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Field label="Job title" required>
              <input
                required
                autoFocus
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Python Developer, Data Engineer, DevOps Engineer…"
                className={inputClass}
              />
            </Field>
            <Field
              label="Your full name"
              hint={knownName ? `Leave empty to use ${knownName}` : undefined}
            >
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder={knownName ?? 'Henry Joseph Itta'}
                className={inputClass}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="submit" loading={saving}>
                Create
              </Button>
              {!!profiles?.length && (
                <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                  Cancel
                </Button>
              )}
            </div>
          </form>
        </Card>
      )}

      {profiles === null && !error ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : profiles && profiles.length === 0 ? (
        <EmptyState
          title="No profiles yet"
          body="Create your first profile above, e.g. “Python Developer”, then upload the resumes you use for that role."
        />
      ) : (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {profiles?.map((p) => (
            <Link
              key={p.profile_id}
              href={`/profiles/${p.profile_id}`}
              className="group rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-200/70 transition hover:shadow-md hover:ring-brand-500"
            >
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50">
                <UserRound className="h-6 w-6 text-brand-600" />
              </div>
              <p className="font-display mt-4 text-lg font-semibold text-gray-900 group-hover:text-brand-700">
                {p.title}
              </p>
              <p className="text-sm text-gray-500">{p.full_name || 'No name set'}</p>
              <div className="mt-4 flex gap-4 text-sm text-gray-600">
                <span className="inline-flex items-center gap-1.5">
                  <FileText className="h-4 w-4" />
                  {p.resume_count} resume{p.resume_count === 1 ? '' : 's'}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <ListChecks className="h-4 w-4" />
                  {p.task_count} task{p.task_count === 1 ? '' : 's'}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
