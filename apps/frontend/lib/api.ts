/**
 * LokiShift API client. All calls go through the Next.js `/api` proxy
 * (next.config.ts rewrites) unless NEXT_PUBLIC_API_URL points elsewhere.
 */

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? '/').trim().replace(/\/+$/, '');
export const API_BASE = `${API_URL}/api/v1`;

export type TaskStatus = 'matching' | 'matched' | 'tailoring' | 'finished' | 'failed';

export interface ExperienceItem {
  title: string;
  company: string;
  location: string;
  work_mode: string;
  domain: string;
  start: string;
  end: string;
}

export interface ResumeFile {
  resume_id: string;
  profile_id: string;
  name: string;
  filename: string;
  size_bytes: number;
  word_count: number;
  created_at: string;
  updated_at: string;
}

export interface Profile {
  profile_id: string;
  title: string;
  full_name: string;
  email: string;
  phone: string;
  linkedin: string;
  location: string;
  total_experience: string;
  summary: string;
  experience: ExperienceItem[];
  created_at: string;
  updated_at: string;
  resume_count?: number;
  task_count?: number;
  resumes?: ResumeFile[];
}

export type ProfileInput = Omit<
  Profile,
  'profile_id' | 'created_at' | 'updated_at' | 'resume_count' | 'task_count' | 'resumes'
>;

export interface Ranking {
  resume_id: string;
  name: string;
  score: number;
  ai_score: number | null;
  keyword_score: number;
  matched_keywords: string[];
  missing_keywords: string[];
  strengths: string[];
  gaps: string[];
  reasoning: string;
}

export interface TailorEdit {
  index: number;
  original_text: string;
  new_text: string;
  keywords: string[];
  added_from_jd: string[];
}

export interface TailorAddition {
  after: number;
  anchor_text: string;
  text: string;
  keywords: string[];
}

export interface TailoringReport {
  summary: string;
  edits: TailorEdit[];
  additions: TailorAddition[];
  keyword_score_before: number;
  keyword_score_after: number;
  matched_after: string[];
  missing_after: string[];
  resume_id: string;
  resume_name: string;
  score_before: number | null;
  score_after: number;
  score_warning: string | null;
  model: string;
  connection?: string;
  backup_used?: boolean;
  failed_connections?: string[];
}

export interface Task {
  task_id: string;
  profile_id: string;
  profile_title: string;
  job_title: string;
  job_location: string;
  vendor_company: string;
  domain: string;
  job_description?: string;
  recruiter_name: string;
  recruiter_email: string;
  vendor_name: string;
  vendor_email: string;
  ai_instructions: string;
  auto_tailor: boolean;
  status: TaskStatus;
  error: string | null;
  /** AI connection chosen for this task (null = default). */
  connection_id: string | null;
  /** "Name (model)" of the connection that ran the last job. */
  llm_used: string | null;
  ranking?: {
    rankings: Ranking[];
    recommended_resume_id: string;
    must_have_skills: string[];
    warning: string | null;
    connection?: string;
    backup_used?: boolean;
    failed_connections?: string[];
  } | null;
  best_resume_id: string | null;
  match_score: number | null;
  tailored_resume_id: string | null;
  tailored_filename: string | null;
  tailoring?: TailoringReport | null;
  tailored_score: number | null;
  has_tailored_docx: boolean;
  seen: boolean;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

export interface TaskInput {
  profile_id: string;
  job_title: string;
  job_location: string;
  vendor_company: string;
  domain: string;
  job_description: string;
  recruiter_name: string;
  recruiter_email: string;
  vendor_name: string;
  vendor_email: string;
  ai_instructions: string;
  auto_tailor: boolean;
  connection_id: string | null;
}

export interface DashboardStats {
  total: number;
  completed: number;
  failed: number;
  in_progress: number;
  ready_to_tailor: number;
  week_start: string;
  week_end: string;
  week_count: number;
  profiles: number;
  resumes: number;
}

export interface Dashboard {
  stats: DashboardStats;
  notifications: Task[];
  queue_size: number;
}

export interface ReportRow {
  name: string;
  tasks: number;
  tailored: number;
  avg_match: number | null;
  last_at: string;
}

export interface Report {
  range: { from: string; to: string; days: number };
  totals: {
    tasks: number;
    tailored: number;
    ready: number;
    running: number;
    failed: number;
    avg_match: number | null;
    avg_tailored: number | null;
    avg_gain: number | null;
    tailored_rate: number;
    vendors: number;
  };
  trend: {
    bucket: 'week' | 'month';
    points: { start: string; end: string; total: number; tailored: number }[];
  };
  vendors: ReportRow[];
  positions: ReportRow[];
  locations: ReportRow[];
  profiles: ReportRow[];
  domains: ReportRow[];
  insights: string[];
}

export interface Connection {
  connection_id: string;
  name: string;
  provider: string;
  provider_label: string;
  model: string;
  api_base: string | null;
  reasoning_effort: string | null;
  /** Whether a key is saved. The key itself is never sent to the browser. */
  has_api_key: boolean;
  needs_api_key: boolean;
  is_default: boolean;
  use_as_backup: boolean;
  position: number;
}

export interface ConnectionInput {
  name: string;
  provider: string;
  model: string;
  /** Write-only. Omit to keep the saved key. */
  api_key?: string;
  api_base?: string | null;
  reasoning_effort?: string | null;
  use_as_backup?: boolean;
  make_default?: boolean;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = typeof FormData !== 'undefined' && init.body instanceof FormData;
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers:
      isForm || !init.body ? init.headers : { 'Content-Type': 'application/json', ...init.headers },
    cache: 'no-store',
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
      else if (Array.isArray(body.detail)) {
        message = body.detail
          .map(
            (d: { loc?: string[]; msg?: string }) => `${d.loc?.slice(-1)[0] ?? ''}: ${d.msg ?? ''}`
          )
          .join('; ');
      }
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  dashboard: () => request<Dashboard>('/dashboard'),

  // profiles
  listProfiles: () => request<{ profiles: Profile[] }>('/profiles').then((r) => r.profiles),
  getProfile: (id: string) => request<Profile>(`/profiles/${id}`),
  createProfile: (values: Partial<ProfileInput> & { title: string }) =>
    request<Profile>('/profiles', { method: 'POST', body: json(values) }),
  updateProfile: (id: string, values: Partial<ProfileInput>) =>
    request<Profile>(`/profiles/${id}`, { method: 'PATCH', body: json(values) }),
  deleteProfile: (id: string) =>
    request<{ deleted: boolean }>(`/profiles/${id}`, { method: 'DELETE' }),

  uploadResume: (profileId: string, file: File, name?: string) => {
    const form = new FormData();
    form.append('file', file);
    if (name) form.append('name', name);
    return request<ResumeFile>(`/profiles/${profileId}/resumes`, { method: 'POST', body: form });
  },
  updateResume: (
    profileId: string,
    resumeId: string,
    values: { name?: string; profile_id?: string }
  ) =>
    request<ResumeFile>(`/profiles/${profileId}/resumes/${resumeId}`, {
      method: 'PATCH',
      body: json(values),
    }),
  deleteResume: (profileId: string, resumeId: string) =>
    request<{ deleted: boolean }>(`/profiles/${profileId}/resumes/${resumeId}`, {
      method: 'DELETE',
    }),
  resumeDownloadUrl: (profileId: string, resumeId: string) =>
    `${API_BASE}/profiles/${profileId}/resumes/${resumeId}/download`,

  // tasks
  listTasks: (
    params: {
      profile_id?: string;
      status?: string;
      q?: string;
      limit?: number;
      created_from?: string;
      created_to?: string;
    } = {}
  ) => {
    const qs = new URLSearchParams(
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== '')
        .map(([k, v]) => [k, String(v)])
    ).toString();
    return request<{ tasks: Task[] }>(`/tasks${qs ? `?${qs}` : ''}`).then((r) => r.tasks);
  },
  getTask: (id: string) => request<Task>(`/tasks/${id}`),
  createTask: (values: TaskInput) =>
    request<Task>('/tasks', { method: 'POST', body: json(values) }),
  tailorTask: (id: string, values: { resume_id?: string; ai_instructions?: string } = {}) =>
    request<Task>(`/tasks/${id}/tailor`, { method: 'POST', body: json(values) }),
  retryTask: (id: string) => request<Task>(`/tasks/${id}/retry`, { method: 'POST' }),
  rematchTask: (id: string) => request<Task>(`/tasks/${id}/rematch`, { method: 'POST' }),
  deleteTask: (id: string) => request<{ deleted: boolean }>(`/tasks/${id}`, { method: 'DELETE' }),
  markSeen: (ids?: string[]) =>
    request<{ updated: number }>('/tasks/seen', {
      method: 'POST',
      body: ids ? json(ids) : undefined,
    }),
  taskDownloadUrl: (id: string) => `${API_BASE}/tasks/${id}/download`,

  report: (days: number) =>
    request<Report>(`/reports?days=${days}&tz_offset=${-new Date().getTimezoneOffset()}`),

  // AI connections
  listConnections: () =>
    request<{ connections: Connection[] }>('/connections').then((r) => r.connections),
  createConnection: (values: ConnectionInput) =>
    request<Connection>('/connections', { method: 'POST', body: json(values) }),
  updateConnection: (id: string, values: Partial<ConnectionInput>) =>
    request<Connection>(`/connections/${id}`, { method: 'PATCH', body: json(values) }),
  setDefaultConnection: (id: string) =>
    request<{ connections: Connection[] }>(`/connections/${id}/default`, { method: 'POST' }).then(
      (r) => r.connections
    ),
  reorderConnections: (ids: string[]) =>
    request<{ connections: Connection[] }>('/connections/reorder', {
      method: 'POST',
      body: json({ connection_ids: ids }),
    }).then((r) => r.connections),
  testConnection: (id: string) =>
    request<{ healthy: boolean; error_code?: string; error_detail?: string }>(
      `/connections/${id}/test`,
      { method: 'POST' }
    ),
  deleteConnection: (id: string) =>
    request<{ connections: Connection[] }>(`/connections/${id}`, { method: 'DELETE' }).then(
      (r) => r.connections
    ),
  status: () =>
    request<{
      status: string;
      llm_configured: boolean;
      llm_healthy: boolean;
      has_resumes: boolean;
    }>('/status'),
};

export const RUNNING: TaskStatus[] = ['matching', 'tailoring'];

export const DOMAINS = [
  'Banking',
  'Finance',
  'Insurance',
  'Healthcare',
  'Pharma',
  'Retail',
  'E-commerce',
  'Manufacturing',
  'Automotive',
  'Telecom',
  'Energy',
  'Government',
  'Technology',
  'Media',
  'Logistics',
  'Education',
];

export function mailVendorHref(task: Task, candidate: string): string | null {
  const to = task.vendor_email || task.recruiter_email;
  if (!to) return null;
  const greeting = task.vendor_name || task.recruiter_name;
  const subject = `${candidate ? `${candidate} - ` : ''}${task.job_title}${task.job_location ? ` (${task.job_location})` : ''}`;
  const body = [
    `Hi${greeting ? ` ${greeting.split(' ')[0]}` : ''},`,
    '',
    `Please find attached my updated resume for the ${task.job_title} position${
      task.job_location ? ` in ${task.job_location}` : ''
    }.`,
    '',
    'Looking forward to hearing from you.',
    '',
    'Thanks,',
    candidate || '',
  ].join('\n');
  const cc =
    task.vendor_email && task.recruiter_email && task.vendor_email !== task.recruiter_email
      ? `&cc=${encodeURIComponent(task.recruiter_email)}`
      : '';
  return `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}${cc}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return formatDate(iso);
}

export type Period = 'this_week' | 'last_week' | 'this_month' | 'all';

export const PERIODS: { value: Period; label: string }[] = [
  { value: 'this_week', label: 'This week' },
  { value: 'last_week', label: 'Last week' },
  { value: 'this_month', label: 'This month' },
  { value: 'all', label: 'All time' },
];

/** ISO range for a period in the user's local time (weeks start on Monday). */
export function periodRange(
  period: Period,
  now = new Date()
): { created_from?: string; created_to?: string } {
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const monday = new Date(startOfDay);
  monday.setDate(startOfDay.getDate() - ((startOfDay.getDay() + 6) % 7));
  if (period === 'this_week') return { created_from: monday.toISOString() };
  if (period === 'last_week') {
    const previous = new Date(monday);
    previous.setDate(monday.getDate() - 7);
    return { created_from: previous.toISOString(), created_to: monday.toISOString() };
  }
  if (period === 'this_month') {
    return { created_from: new Date(now.getFullYear(), now.getMonth(), 1).toISOString() };
  }
  return {};
}
