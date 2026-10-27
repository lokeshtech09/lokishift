'use client';

import {
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  KeyRound,
  Pencil,
  Plug,
  Plus,
  Star,
  Trash2,
  XCircle,
} from 'lucide-react';
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
import { api, type Connection, type ConnectionInput } from '@/lib/api';
import { cn } from '@/lib/utils';

const PROVIDERS = [
  { id: 'openai', label: 'OpenAI', model: 'gpt-5.4-mini' },
  { id: 'anthropic', label: 'Anthropic', model: 'claude-sonnet-5-5' },
  { id: 'gemini', label: 'Google Gemini', model: 'gemini-3.5-flash' },
  { id: 'openrouter', label: 'OpenRouter', model: '' },
  { id: 'deepseek', label: 'DeepSeek', model: 'deepseek-chat' },
  { id: 'groq', label: 'Groq', model: '' },
  { id: 'azure_foundry', label: 'Azure AI Foundry', model: '' },
  { id: 'ollama', label: 'Ollama (local)', model: 'llama3.3' },
  { id: 'openai_compatible', label: 'OpenAI-compatible server', model: '' },
];
const LOCAL = new Set(['ollama', 'openai_compatible']);

export default function SettingsPage() {
  const [connections, setConnections] = useState<Connection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | 'new' | null>(null);

  const load = async () => {
    try {
      const list = await api.listConnections();
      setConnections(list);
      if (list.length === 0) setEditing('new');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load connections.');
    }
  };

  useEffect(() => {
    load();
  }, []);

  const run = async (fn: () => Promise<Connection[] | unknown>) => {
    setError(null);
    try {
      const result = await fn();
      if (Array.isArray(result)) setConnections(result as Connection[]);
      else await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.');
    }
  };

  const move = (index: number, delta: number) => {
    if (!connections) return;
    const ids = connections.map((c) => c.connection_id);
    const [id] = ids.splice(index, 1);
    ids.splice(index + delta, 0, id);
    run(() => api.reorderConnections(ids));
  };

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Your AI connections: the provider, model and key that score and tailor your resumes. This is the only place keys are added."
      />
      <ErrorBanner message={error} />

      <Card className="mt-2">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-lg font-semibold text-gray-900">AI connections</h2>
            <p className="mt-1 max-w-2xl text-sm text-gray-500">
              Tasks run on the{' '}
              <Star className="inline h-3.5 w-3.5 fill-accent-500 text-accent-500" /> default. If it
              fails (no credit, quota used up, provider down, key rejected), LokiShift automatically
              tries the connections marked <em>backup</em>, from top to bottom.
            </p>
          </div>
          {editing !== 'new' && (
            <Button onClick={() => setEditing('new')}>
              <Plus className="h-4 w-4" />
              Add connection
            </Button>
          )}
        </div>

        {editing === 'new' && (
          <ConnectionForm
            isFirst={!connections?.length}
            onCancel={connections?.length ? () => setEditing(null) : undefined}
            onSaved={() => {
              setEditing(null);
              load();
            }}
          />
        )}

        {connections === null && !error ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : connections && connections.length === 0 && editing !== 'new' ? (
          <EmptyState title="No connections yet" body="Add one to start matching and tailoring." />
        ) : (
          <ul className="mt-5 space-y-3">
            {connections?.map((c, i) =>
              editing === c.connection_id ? (
                <li key={c.connection_id}>
                  <ConnectionForm
                    existing={c}
                    onCancel={() => setEditing(null)}
                    onSaved={() => {
                      setEditing(null);
                      load();
                    }}
                  />
                </li>
              ) : (
                <ConnectionRow
                  key={c.connection_id}
                  connection={c}
                  first={i === 0}
                  last={i === connections.length - 1}
                  onDefault={() => run(() => api.setDefaultConnection(c.connection_id))}
                  onBackup={(value) =>
                    run(() => api.updateConnection(c.connection_id, { use_as_backup: value }))
                  }
                  onUp={() => move(i, -1)}
                  onDown={() => move(i, 1)}
                  onEdit={() => setEditing(c.connection_id)}
                  onDelete={() => {
                    const extra =
                      c.is_default && connections.length > 1
                        ? ' The next connection becomes the default.'
                        : '';
                    if (confirm(`Delete “${c.name}”? Its saved key is removed too.${extra}`)) {
                      run(() => api.deleteConnection(c.connection_id));
                    }
                  }}
                />
              )
            )}
          </ul>
        )}
      </Card>
    </>
  );
}

function ConnectionRow({
  connection: c,
  first,
  last,
  onDefault,
  onBackup,
  onUp,
  onDown,
  onEdit,
  onDelete,
}: {
  connection: Connection;
  first: boolean;
  last: boolean;
  onDefault: () => void;
  onBackup: (value: boolean) => void;
  onUp: () => void;
  onDown: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const test = async () => {
    setTesting(true);
    setResult(null);
    try {
      const r = await api.testConnection(c.connection_id);
      setResult(
        r.healthy
          ? { ok: true, text: 'Connected — the model answered.' }
          : {
              ok: false,
              text:
                (r.error_detail ?? '')
                  .replace(/```\w*\n?/g, '')
                  .trim()
                  .slice(0, 300) || 'The provider did not answer. Check the key and model.',
            }
      );
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : 'Test failed.' });
    } finally {
      setTesting(false);
    }
  };

  const keyOk = c.needs_api_key ? c.has_api_key : Boolean(c.api_base);

  return (
    <li
      className={cn(
        'rounded-xl border p-4 transition',
        c.is_default ? 'border-brand-300 bg-brand-50/60' : 'border-gray-200 bg-white'
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={onDefault}
          disabled={c.is_default}
          title={c.is_default ? 'Default connection' : 'Make default'}
          aria-label={c.is_default ? 'Default connection' : `Make ${c.name} the default`}
          className={cn(
            'rounded-lg p-1.5 transition',
            c.is_default ? 'cursor-default' : 'text-gray-300 hover:bg-white hover:text-accent-500'
          )}
        >
          <Star className={cn('h-5 w-5', c.is_default && 'fill-accent-500 text-accent-500')} />
        </button>

        <div className="min-w-[11rem] flex-1">
          <p className="flex flex-wrap items-center gap-2 font-semibold text-gray-900">
            {c.name}
            {c.is_default && (
              <span className="rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-brand-800 ring-1 ring-brand-200">
                Default
              </span>
            )}
          </p>
          <p className="text-sm text-gray-500">
            {c.provider_label} · {c.model}
            {c.reasoning_effort ? ` · ${c.reasoning_effort} effort` : ''}
          </p>
        </div>

        <span
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
            keyOk ? 'bg-brand-100 text-brand-800' : 'bg-red-50 text-red-700'
          )}
        >
          <KeyRound className="h-3.5 w-3.5" />
          {c.needs_api_key
            ? c.has_api_key
              ? 'Key saved'
              : 'No key'
            : c.api_base
              ? 'Local server'
              : 'No URL'}
        </span>

        {!c.is_default && (
          <label
            className="flex cursor-pointer items-center gap-2 text-sm text-gray-600"
            title="Try this connection when the default fails"
          >
            <input
              type="checkbox"
              checked={c.use_as_backup}
              onChange={(e) => onBackup(e.target.checked)}
              className="h-4 w-4 accent-brand-600"
            />
            Backup
          </label>
        )}

        <div className="ml-auto flex items-center gap-0.5">
          <IconButton label="Move up" onClick={onUp} disabled={first} icon={ArrowUp} />
          <IconButton label="Move down" onClick={onDown} disabled={last} icon={ArrowDown} />
          <IconButton label="Test connection" onClick={test} disabled={testing} icon={Plug} />
          <IconButton label="Edit" onClick={onEdit} icon={Pencil} />
          <IconButton label="Delete" onClick={onDelete} icon={Trash2} danger />
        </div>
      </div>
      {(testing || result) && (
        <p
          className={cn(
            'mt-3 flex items-start gap-2 text-sm sm:pl-11',
            testing ? 'text-gray-500' : result?.ok ? 'text-brand-700' : 'text-red-700'
          )}
        >
          {testing ? (
            <Spinner className="h-4 w-4" />
          ) : result?.ok ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          {testing ? 'Testing…' : result?.text}
        </p>
      )}
    </li>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  icon: Icon,
  danger,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  icon: React.ComponentType<{ className?: string }>;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      className={cn(
        'rounded-lg p-2 text-gray-500 transition disabled:cursor-not-allowed disabled:opacity-30',
        danger ? 'hover:bg-red-50 hover:text-red-600' : 'hover:bg-gray-100 hover:text-gray-900'
      )}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}

function ConnectionForm({
  existing,
  isFirst,
  onCancel,
  onSaved,
}: {
  existing?: Connection;
  isFirst?: boolean;
  onCancel?: () => void;
  onSaved: () => void;
}) {
  const [provider, setProvider] = useState(existing?.provider ?? 'openai');
  const meta = PROVIDERS.find((p) => p.id === provider)!;
  const [name, setName] = useState(existing?.name ?? meta.label);
  const [nameTouched, setNameTouched] = useState(Boolean(existing));
  const [model, setModel] = useState(existing?.model ?? meta.model);
  const [apiKey, setApiKey] = useState('');
  const [apiBase, setApiBase] = useState(existing?.api_base ?? '');
  const [effort, setEffort] = useState(existing?.reasoning_effort ?? '');
  const [makeDefault, setMakeDefault] = useState(Boolean(isFirst));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const local = LOCAL.has(provider);
  const showBase = local || provider === 'azure_foundry' || Boolean(apiBase);
  const keySaved = Boolean(existing?.has_api_key) && existing?.provider === provider;

  const changeProvider = (id: string) => {
    setProvider(id);
    const next = PROVIDERS.find((p) => p.id === id)!;
    if (!existing || !model) setModel(next.model);
    if (!nameTouched) setName(next.label);
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const values: ConnectionInput = {
      name: name.trim(),
      provider,
      model: model.trim(),
      api_base: apiBase.trim() || null,
      reasoning_effort: effort || null,
    };
    if (apiKey.trim()) values.api_key = apiKey.trim();
    try {
      if (existing) await api.updateConnection(existing.connection_id, values);
      else await api.createConnection({ ...values, make_default: makeDefault });
      setApiKey('');
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.');
      setSaving(false);
    }
  };

  return (
    <form
      onSubmit={save}
      className="mt-5 space-y-5 rounded-xl border border-brand-200 bg-gray-50/60 p-5"
    >
      <p className="font-display font-semibold text-gray-900">
        {existing ? `Edit “${existing.name}”` : 'New connection'}
      </p>
      <div className="grid gap-5 sm:grid-cols-2">
        <Field label="Provider" required>
          <select
            value={provider}
            onChange={(e) => changeProvider(e.target.value)}
            className={inputClass}
          >
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Name" required hint="Shown in lists, e.g. “OpenAI – work”.">
          <input
            required
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setNameTouched(true);
            }}
            className={inputClass}
          />
        </Field>
        <Field label="Model" required hint="Exact model name from the provider.">
          <input
            required
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Reasoning effort" hint="Optional. Lower is faster; higher is more careful.">
          <select value={effort} onChange={(e) => setEffort(e.target.value)} className={inputClass}>
            <option value="">Provider default</option>
            <option value="minimal">Minimal</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </Field>
      </div>
      {!local && (
        <Field
          label="API key"
          required={!keySaved}
          hint={
            keySaved
              ? 'A key is saved. Paste a new one only to replace it.'
              : 'Encrypted and kept on this computer. It is never shown again or sent to your browser.'
          }
        >
          <div className="relative">
            <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="password"
              autoComplete="new-password"
              spellCheck={false}
              required={!keySaved}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={keySaved ? '✓ Key saved' : 'Paste your API key'}
              className={`${inputClass} pl-9`}
            />
          </div>
        </Field>
      )}
      {showBase && (
        <Field
          label="Base URL"
          required={local || provider === 'azure_foundry'}
          hint="e.g. http://localhost:11434 for Ollama"
        >
          <input
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            className={inputClass}
          />
        </Field>
      )}
      {!existing && !isFirst && (
        <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            checked={makeDefault}
            onChange={(e) => setMakeDefault(e.target.checked)}
            className="h-4 w-4 accent-brand-600"
          />
          Make this the default connection
        </label>
      )}
      <ErrorBanner message={error} />
      <div className="flex gap-2">
        <Button type="submit" loading={saving}>
          {existing ? 'Save changes' : 'Add connection'}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
