import { X } from 'lucide-react';
import type { Health, Provider, Settings } from '../types';

interface Props {
  open: boolean;
  onClose: () => void;
  settings: Settings;
  onChange: (s: Settings) => void;
  health: Health | null;
}

const PROVIDERS: { id: Provider; name: string; search: string; keyHint: string; keyUrl: string }[] = [
  { id: 'gemini', name: 'Google Gemini', search: 'Google Search grounding', keyHint: 'AIza…', keyUrl: 'https://aistudio.google.com/apikey' },
  { id: 'openai', name: 'OpenAI', search: 'OpenAI web search', keyHint: 'sk-…', keyUrl: 'https://platform.openai.com/api-keys' },
];

const FALLBACK_MODELS: Record<Provider, string[]> = {
  gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-lite'],
  openai: ['gpt-4.1-mini', 'gpt-4.1', 'gpt-4o', 'gpt-4o-mini'],
};

export function SettingsDrawer({ open, onClose, settings, onChange, health }: Props) {
  if (!open) return null;
  const info = health?.providers?.[settings.provider];
  const models = info?.models ?? FALLBACK_MODELS[settings.provider];
  const current = PROVIDERS.find((p) => p.id === settings.provider)!;

  const switchProvider = (provider: Provider) =>
    onChange({
      ...settings,
      provider,
      apiKey: '',
      model: health?.providers?.[provider]?.default_model ?? FALLBACK_MODELS[provider][0],
    });

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/20 no-print" onClick={onClose}>
      <aside
        className="h-full w-full max-w-sm overflow-y-auto border-l border-rule bg-paper p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Settings"
      >
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-serif text-2xl font-semibold">Settings</h2>
          <button onClick={onClose} aria-label="Close settings" className="text-muted hover:text-ink">
            <X className="h-5 w-5" />
          </button>
        </div>

        <p className="text-sm font-semibold">AI provider</p>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
          {PROVIDERS.map((p) => {
            const ready = health?.providers?.[p.id]?.server_key;
            return (
              <button
                key={p.id}
                onClick={() => switchProvider(p.id)}
                className={`rounded-lg border px-3 py-2 text-left text-sm ${
                  settings.provider === p.id ? 'border-ink bg-white' : 'border-rule hover:border-ink/50'
                }`}
              >
                <span className="block font-semibold">{p.name}</span>
                <span className="block text-xs text-muted">{ready ? 'Ready' : 'Needs your key'}</span>
              </button>
            );
          })}
        </div>
        <p className="mt-1.5 text-xs text-muted">Claims are checked live with {current.search}.</p>

        <label className="mt-6 block text-sm font-semibold">{current.name} API key</label>
        <input
          type="password"
          autoComplete="off"
          placeholder={info?.server_key ? 'Optional: the app has its own key' : current.keyHint}
          value={settings.apiKey}
          onChange={(e) => onChange({ ...settings, apiKey: e.target.value })}
          className="mt-1.5 w-full rounded-md border border-rule bg-white px-3 py-2 text-sm outline-none focus:border-ink"
        />
        <p className="mt-1.5 text-xs text-muted">
          {info?.server_key ? 'Only needed if the app hits its limits. ' : (
            <>
              Get one at{' '}
              <a href={current.keyUrl} target="_blank" rel="noreferrer" className="underline hover:text-pen">
                {new URL(current.keyUrl).hostname}
              </a>
              .{' '}
            </>
          )}
          Kept in this tab's memory and sent only with your requests; never stored.
        </p>

        <label className="mt-6 block text-sm font-semibold">Model</label>
        <select
          value={settings.model}
          onChange={(e) => onChange({ ...settings, model: e.target.value })}
          className="mt-1.5 w-full rounded-md border border-rule bg-white px-3 py-2 text-sm outline-none focus:border-ink"
        >
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
              {m === info?.default_model ? ' (default)' : ''}
            </option>
          ))}
        </select>
        <p className="mt-1.5 text-xs text-muted">Larger models catch subtler errors but are slower.</p>

        <label className="mt-6 block text-sm font-semibold">
          Max claims to check: <span className="font-serif">{settings.maxClaims}</span>
        </label>
        <input
          type="range"
          min={5}
          max={40}
          value={settings.maxClaims}
          onChange={(e) => onChange({ ...settings, maxClaims: Number(e.target.value) })}
          className="mt-2 w-full accent-pen"
        />
        <p className="mt-1.5 text-xs text-muted">Fewer claims finish faster on free-tier keys.</p>
      </aside>
    </div>
  );
}
