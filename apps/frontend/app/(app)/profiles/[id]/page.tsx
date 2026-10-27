'use client';

import { ArrowLeft, Download, FileUp, Pencil, Plus, Trash2, Upload, X } from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Button,
  buttonClass,
  Card,
  ErrorBanner,
  Field,
  inputClass,
  Spinner,
} from '@/components/ui';
import {
  api,
  DOMAINS,
  formatDate,
  type ExperienceItem,
  type Profile,
  type ProfileInput,
  type ResumeFile,
} from '@/lib/api';
import { cn } from '@/lib/utils';
import { DownloadLink } from '@/components/download-link';

const EMPTY_ROLE: ExperienceItem = {
  title: '',
  company: '',
  location: '',
  work_mode: '',
  domain: '',
  start: '',
  end: '',
};

export default function ProfilePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [others, setOthers] = useState<Profile[]>([]);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, all] = await Promise.all([api.getProfile(id), api.listProfiles()]);
      setProfile(p);
      setOthers(all.filter((x) => x.profile_id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the profile.');
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !profile) return <ErrorBanner message={error} />;
  if (!profile)
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );

  const remove = async () => {
    if (
      !confirm(
        `Delete the “${profile.title}” profile and its ${profile.resumes?.length ?? 0} resumes? Tasks are kept.`
      )
    )
      return;
    await api.deleteProfile(profile.profile_id);
    router.push('/profiles');
  };

  return (
    <>
      <div className="mb-6 flex items-center justify-between">
        <Link
          href="/profiles"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-gray-600 hover:text-gray-900"
        >
          <ArrowLeft className="h-4 w-4" />
          All profiles
        </Link>
        <div className="flex gap-2">
          <Link
            href={`/tasks/new?profile=${profile.profile_id}`}
            className={buttonClass('secondary')}
          >
            <Plus className="h-4 w-4" />
            New task
          </Link>
          {!editing && (
            <Button onClick={() => setEditing(true)}>
              <Pencil className="h-4 w-4" />
              Edit Profile
            </Button>
          )}
        </div>
      </div>

      {editing ? (
        <ProfileEditor
          profile={profile}
          onCancel={() => setEditing(false)}
          onSaved={(p) => {
            setProfile({ ...profile, ...p });
            setEditing(false);
          }}
          onDelete={remove}
        />
      ) : (
        <ProfileView profile={profile} />
      )}

      <Resumes profile={profile} others={others} onChanged={load} />
    </>
  );
}

function ProfileView({ profile }: { profile: Profile }) {
  return (
    <Card className="p-8 sm:p-10">
      <div className="text-center">
        <h1 className="font-display text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl">
          {profile.full_name || 'Your name'}
        </h1>
        <p className="mt-2 text-xl text-gray-600">{profile.title}</p>
        {[profile.phone, profile.email, profile.location].filter(Boolean).length > 0 && (
          <p className="mt-1 text-gray-700">
            {[profile.phone, profile.email, profile.location].filter(Boolean).join(' · ')}
          </p>
        )}
        {profile.linkedin && (
          <a
            href={profile.linkedin}
            target="_blank"
            rel="noreferrer"
            className="mt-1 block break-all text-gray-700 hover:text-brand-600"
          >
            {profile.linkedin}
          </a>
        )}
      </div>

      {profile.total_experience && (
        <div className="mt-10">
          <p className="text-sm font-semibold text-gray-600">Total Experience</p>
          <p className="text-lg text-gray-900">{profile.total_experience}</p>
        </div>
      )}
      {profile.summary && (
        <p className="mt-4 whitespace-pre-line text-gray-700">{profile.summary}</p>
      )}

      <h2 className="mt-8 text-2xl font-semibold text-gray-900">Experience</h2>
      {profile.experience.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500">
          No roles added yet. Use Edit Profile to add your work history.
        </p>
      ) : (
        <div className="mt-4 divide-y divide-gray-100">
          {profile.experience.map((role, i) => (
            <div key={i} className="flex flex-wrap justify-between gap-2 py-5">
              <div>
                <p className="font-display text-xl font-semibold text-gray-900">{role.title}</p>
                <p className="mt-1 text-gray-500">
                  {[
                    [role.start, role.end || 'Present'].filter(Boolean).join(' – '),
                    role.location,
                    role.work_mode,
                  ]
                    .filter(Boolean)
                    .join('  •  ')}
                </p>
                {role.domain && (
                  <p className="mt-2 text-gray-700">
                    <span className="font-semibold">Domain:</span> {role.domain}
                  </p>
                )}
              </div>
              <p className="text-lg font-medium text-gray-600">{role.company}</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function ProfileEditor({
  profile,
  onCancel,
  onSaved,
  onDelete,
}: {
  profile: Profile;
  onCancel: () => void;
  onSaved: (p: Profile) => void;
  onDelete: () => void;
}) {
  const [form, setForm] = useState<ProfileInput>({
    title: profile.title,
    full_name: profile.full_name,
    email: profile.email,
    phone: profile.phone,
    linkedin: profile.linkedin,
    location: profile.location,
    total_experience: profile.total_experience,
    summary: profile.summary,
    experience: profile.experience.length ? profile.experience : [],
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof ProfileInput>(key: K, value: ProfileInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  const setRole = (i: number, key: keyof ExperienceItem, value: string) =>
    set(
      'experience',
      form.experience.map((r, j) => (j === i ? { ...r, [key]: value } : r))
    );

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await api.updateProfile(profile.profile_id, {
          ...form,
          experience: form.experience.filter((r) => r.title || r.company),
        })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.');
      setSaving(false);
    }
  };

  return (
    <Card className="p-8">
      <form onSubmit={save} className="space-y-8">
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Job title (profile name)" required>
            <input
              required
              value={form.title}
              onChange={(e) => set('title', e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Full name">
            <input
              value={form.full_name}
              onChange={(e) => set('full_name', e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Phone">
            <input
              value={form.phone}
              onChange={(e) => set('phone', e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Email">
            <input
              type="email"
              value={form.email}
              onChange={(e) => set('email', e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="LinkedIn URL">
            <input
              value={form.linkedin}
              onChange={(e) => set('linkedin', e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Location">
            <input
              value={form.location}
              onChange={(e) => set('location', e.target.value)}
              placeholder="Austin, TX"
              className={inputClass}
            />
          </Field>
          <Field label="Total experience">
            <input
              value={form.total_experience}
              onChange={(e) => set('total_experience', e.target.value)}
              placeholder="10 years"
              className={inputClass}
            />
          </Field>
        </div>
        <Field label="Summary / notes">
          <textarea
            rows={3}
            value={form.summary}
            onChange={(e) => set('summary', e.target.value)}
            className={inputClass}
          />
        </Field>

        <div>
          <div className="mb-3 flex items-center justify-between">
            <h3 className="font-display text-lg font-semibold text-gray-900">Experience</h3>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => set('experience', [...form.experience, { ...EMPTY_ROLE }])}
            >
              <Plus className="h-4 w-4" />
              Add role
            </Button>
          </div>
          <div className="space-y-4">
            {form.experience.map((role, i) => (
              <div
                key={i}
                className="relative grid gap-3 rounded-xl border border-gray-200 p-4 sm:grid-cols-3"
              >
                <input
                  value={role.title}
                  onChange={(e) => setRole(i, 'title', e.target.value)}
                  placeholder="Job title"
                  className={inputClass}
                />
                <input
                  value={role.company}
                  onChange={(e) => setRole(i, 'company', e.target.value)}
                  placeholder="Company"
                  className={inputClass}
                />
                <input
                  value={role.location}
                  onChange={(e) => setRole(i, 'location', e.target.value)}
                  placeholder="Location"
                  className={inputClass}
                />
                <input
                  value={role.start}
                  onChange={(e) => setRole(i, 'start', e.target.value)}
                  placeholder="Start (e.g. Jan 2021)"
                  className={inputClass}
                />
                <input
                  value={role.end}
                  onChange={(e) => setRole(i, 'end', e.target.value)}
                  placeholder="End (empty = Present)"
                  className={inputClass}
                />
                <div className="flex gap-2">
                  <select
                    value={role.work_mode}
                    onChange={(e) => setRole(i, 'work_mode', e.target.value)}
                    className={inputClass}
                  >
                    <option value="">Mode</option>
                    <option>onsite</option>
                    <option>hybrid</option>
                    <option>remote</option>
                  </select>
                  <select
                    value={role.domain}
                    onChange={(e) => setRole(i, 'domain', e.target.value)}
                    className={inputClass}
                  >
                    <option value="">Domain</option>
                    {DOMAINS.map((d) => (
                      <option key={d}>{d}</option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    set(
                      'experience',
                      form.experience.filter((_, j) => j !== i)
                    )
                  }
                  className="absolute -right-2 -top-2 rounded-full bg-white p-1 text-gray-400 shadow ring-1 ring-gray-200 hover:text-red-600"
                  aria-label="Remove role"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </div>

        <ErrorBanner message={error} />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button type="button" variant="danger" onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
            Delete profile
          </Button>
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Save profile
            </Button>
          </div>
        </div>
      </form>
    </Card>
  );
}

function Resumes({
  profile,
  others,
  onChanged,
}: {
  profile: Profile;
  others: Profile[];
  onChanged: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resumes = profile.resumes ?? [];

  const upload = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setError(null);
    setUploading(list.length);
    const failures: string[] = [];
    for (const file of list) {
      try {
        await api.uploadResume(profile.profile_id, file);
      } catch (e) {
        failures.push(`${file.name}: ${e instanceof Error ? e.message : 'upload failed'}`);
      }
      setUploading((n) => n - 1);
    }
    if (failures.length) setError(failures.join(' · '));
    onChanged();
  };

  return (
    <Card className="mt-8">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold text-gray-900">
            Resumes for {profile.title}
          </h2>
          <p className="text-sm text-gray-500">
            Every task scores all of these and tailors the best one. Word (.docx) only — your
            formatting is kept.
          </p>
        </div>
        <Button onClick={() => input.current?.click()} loading={uploading > 0}>
          <Upload className="h-4 w-4" />
          Upload resumes
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="hidden"
          onChange={(e) => {
            if (e.target.files) upload(e.target.files);
            e.target.value = '';
          }}
        />
      </div>
      <ErrorBanner message={error} />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          upload(e.dataTransfer.files);
        }}
        className={cn(
          'mt-3 rounded-xl transition',
          dragging && 'ring-2 ring-brand-500 ring-offset-4'
        )}
      >
        {resumes.length === 0 ? (
          <button
            onClick={() => input.current?.click()}
            className="flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed border-gray-300 py-12 text-gray-500 hover:border-brand-500 hover:text-brand-600"
          >
            <FileUp className="h-8 w-8" />
            <span className="font-medium">Drop .docx resumes here or click to upload</span>
          </button>
        ) : (
          <div className="divide-y divide-gray-100">
            {resumes.map((r) => (
              <ResumeRow key={r.resume_id} resume={r} others={others} onChanged={onChanged} />
            ))}
            <p className="pt-4 text-center text-xs text-gray-400">
              Drop more .docx files here to add them
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}

function ResumeRow({
  resume,
  others,
  onChanged,
}: {
  resume: ResumeFile;
  others: Profile[];
  onChanged: () => void;
}) {
  const [name, setName] = useState(resume.name);
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3 py-3.5">
      <FileUp className="h-5 w-5 shrink-0 text-brand-600" />
      <div className="min-w-0 flex-1">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() =>
            name.trim() &&
            name !== resume.name &&
            run(() => api.updateResume(resume.profile_id, resume.resume_id, { name: name.trim() }))
          }
          className="w-full rounded-md border border-transparent bg-transparent px-1 py-0.5 font-medium text-gray-900 hover:border-gray-200 focus:border-brand-500 focus:outline-none"
          aria-label="Resume name"
        />
        <p className="px-1 text-xs text-gray-500">
          {resume.filename} · {resume.word_count.toLocaleString()} words · added{' '}
          {formatDate(resume.created_at)}
          {error && <span className="ml-2 text-red-600">{error}</span>}
        </p>
      </div>
      {others.length > 0 && (
        <select
          value=""
          onChange={(e) =>
            e.target.value &&
            run(() =>
              api.updateResume(resume.profile_id, resume.resume_id, { profile_id: e.target.value })
            )
          }
          className="rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-700"
          aria-label="Move to profile"
        >
          <option value="">Move to…</option>
          {others.map((p) => (
            <option key={p.profile_id} value={p.profile_id}>
              {p.title}
            </option>
          ))}
        </select>
      )}
      <DownloadLink
        href={api.resumeDownloadUrl(resume.profile_id, resume.resume_id)}
        filename={resume.filename}
        className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
        title="Download"
      >
        <Download className="h-4 w-4" />
      </DownloadLink>
      <button
        onClick={() =>
          confirm(`Delete “${resume.name}”?`) &&
          run(() => api.deleteResume(resume.profile_id, resume.resume_id))
        }
        className="rounded-lg p-2 text-gray-500 hover:bg-red-50 hover:text-red-600"
        title="Delete"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}
