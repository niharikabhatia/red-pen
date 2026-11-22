import type {
  Claim, ClaimResult, Contradiction, Correction, Health, PageText, Settings,
} from '../types';

export class ApiError extends Error {
  status: number;
  retryAfter: number; // seconds; > 0 means "temporary, try again later"
  constructor(message: string, status: number, retryAfter = 0) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

async function post<T>(path: string, body: unknown, settings: Settings, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-LLM-Provider': settings.provider,
  };
  if (settings.apiKey.trim()) headers['X-API-Key'] = settings.apiKey.trim();
  if (settings.model) headers['X-LLM-Model'] = settings.model;

  let res: Response;
  try {
    res = await fetch(path, { method: 'POST', headers, body: JSON.stringify(body), signal });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError('Could not reach the server. Check your connection and try again.', 0, 10);
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    let retryAfter = Number(res.headers.get('Retry-After')) || 0;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
      if (typeof data.retry_after === 'number') retryAfter = data.retry_after;
    } catch {
      if (res.status === 504) detail = 'The check timed out.';
    }
    if (res.status === 429 && !retryAfter) retryAfter = 20;
    if (res.status === 504 && !retryAfter) retryAfter = 5; // serverless timeout: worth one more try
    throw new ApiError(detail, res.status, retryAfter);
  }
  return res.json() as Promise<T>;
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(new DOMException('Aborted', 'AbortError'));
    });
  });

/**
 * Retry temporary failures (rate limits, overload, timeouts) with back-off.
 * `onWait(seconds)` is called before each pause so the UI can say what is happening.
 */
export async function withRetry<T>(
  fn: () => Promise<T>,
  opts: { signal?: AbortSignal; onWait?: (seconds: number) => void; attempts?: number } = {},
): Promise<T> {
  const attempts = opts.attempts ?? 5;
  for (let i = 1; ; i++) {
    try {
      return await fn();
    } catch (err) {
      const retryAfter = err instanceof ApiError ? err.retryAfter : 0;
      if (!retryAfter || i >= attempts || opts.signal?.aborted) throw err;
      const wait = Math.max(retryAfter, [0, 0, 20, 30, 45][i] ?? 45);
      opts.onWait?.(wait);
      await sleep(wait * 1000, opts.signal);
    }
  }
}

export async function getHealth(): Promise<Health | null> {
  try {
    const res = await fetch('/api/health');
    return res.ok ? ((await res.json()) as Health) : null;
  } catch {
    return null;
  }
}

export const extractClaims = (pages: PageText[], s: Settings, signal?: AbortSignal) =>
  post<{ claims: Claim[] }>('/api/extract', { pages, max_claims: s.maxClaims }, s, signal).then((r) => r.claims);

export const verifyClaim = (claim: Claim, s: Settings, previous?: ClaimResult, signal?: AbortSignal) =>
  post<ClaimResult>('/api/verify', { claim, previous: previous ?? null }, s, signal);

export const findContradictions = (claims: Claim[], s: Settings, signal?: AbortSignal) =>
  post<{ contradictions: Contradiction[] }>('/api/consistency', { claims }, s, signal).then((r) => r.contradictions);

export const correctDocument = (claims: Claim[], results: ClaimResult[], s: Settings, signal?: AbortSignal) =>
  post<{ corrections: Correction[] }>('/api/correct', { claims, results }, s, signal).then((r) => r.corrections);
