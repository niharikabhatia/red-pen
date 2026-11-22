import { useCallback, useMemo, useRef, useState } from 'react';
import { ApiError, correctDocument, extractClaims, findContradictions, verifyClaim, withRetry } from '../lib/api';
import { buildHighlights, type Highlight } from '../lib/highlight';
import { MAX_FILE_MB, openPdf, readLayouts, toPageTexts, type PageLayout, type PDFDocumentProxy } from '../lib/pdf';
import { runPool } from '../lib/pool';
import type {
  Claim, ClaimResult, ClaimStatus, Contradiction, Correction, Settings, Stage,
} from '../types';

// Two checks at a time keeps free / low-tier API keys under their rate limits.
const CONCURRENCY = 2;

export interface FactCheckState {
  stage: Stage;
  error: string | null;
  filename: string;
  doc: PDFDocumentProxy | null;
  fileBytes: ArrayBuffer | null; // untouched copy of the PDF, for the marked-up report
  layouts: PageLayout[];
  claims: Claim[];
  status: Record<number, ClaimStatus>;
  results: Record<number, ClaimResult>;
  contradictions: Contradiction[];
  corrections: Correction[];
  reviewError: string | null; // consistency/correction failures don't fail the report
  pausedUntil: number | null; // set while waiting out a rate limit (epoch ms)
  startedAt: number | null;
  finishedAt: number | null;
}

const initial: FactCheckState = {
  stage: 'idle', error: null, filename: '', doc: null, fileBytes: null, layouts: [], claims: [], status: {}, results: {},
  contradictions: [], corrections: [], reviewError: null, pausedUntil: null, startedAt: null, finishedAt: null,
};

const errorResult = (claim: Claim, message: string): ClaimResult => ({
  claim_id: claim.id, verdict: 'Error', correct_fact: '', explanation: message,
  evidence_quote: '', confidence: 0, sources: [], second_opinion: false,
});

export function useFactCheck(settings: Settings) {
  const [state, setState] = useState<FactCheckState>(initial);
  const abortRef = useRef<AbortController | null>(null);
  const patch = (p: Partial<FactCheckState> | ((s: FactCheckState) => Partial<FactCheckState>)) =>
    setState((s) => ({ ...s, ...(typeof p === 'function' ? p(s) : p) }));

  const pause = (seconds: number) => patch({ pausedUntil: Date.now() + seconds * 1000 });
  const resume = () => patch((s) => (s.pausedUntil ? { pausedUntil: null } : {}));

  const reset = useCallback(() => {
    abortRef.current?.abort();
    state.doc?.destroy();
    setState(initial);
  }, [state.doc]);

  /** Verify claims (2 at a time) with rate-limit waits and a second opinion when unsure. */
  const verifyAll = useCallback(
    async (claims: Claim[], signal: AbortSignal): Promise<Record<number, ClaimResult>> => {
      const results: Record<number, ClaimResult> = {};
      const setStatus = (id: number, status: ClaimStatus, result?: ClaimResult) =>
        patch((s) => ({
          status: { ...s.status, [id]: status },
          ...(result ? { results: { ...s.results, [id]: result } } : {}),
        }));

      await runPool(claims, CONCURRENCY, async (claim) => {
        setStatus(claim.id, 'checking');
        let limited = false;
        const onWait = (sec: number) => {
          limited = true;
          setStatus(claim.id, 'waiting');
          pause(sec);
        };
        let result: ClaimResult;
        try {
          result = await withRetry(() => verifyClaim(claim, settings, undefined, signal), { signal, onWait });
          resume();
          // Second opinion only when unsure, and skipped under rate-limit pressure.
          if (result.needs_second_opinion && !limited && !signal.aborted) {
            setStatus(claim.id, 'rechecking', result);
            const first = result;
            result = await withRetry(() => verifyClaim(claim, settings, first, signal), {
              signal, attempts: 2, onWait: (sec) => pause(sec),
            }).catch(() => ({ ...first, second_opinion: true }));
            resume();
          }
        } catch (err) {
          if (signal.aborted) return;
          resume();
          result = errorResult(claim, (err as Error).message);
        }
        results[claim.id] = result;
        setStatus(claim.id, 'done', result);
      }, signal);
      return results;
    },
    [settings],
  );

  /** Document-level review: contradictions + corrected version. */
  const review = useCallback(
    async (claims: Claim[], results: ClaimResult[], signal: AbortSignal) => {
      patch({ stage: 'reviewing' });
      const opts = { signal, attempts: 3, onWait: (sec: number) => pause(sec) };
      const [consistency, corrections] = await Promise.allSettled([
        withRetry(() => findContradictions(claims, settings, signal), opts),
        withRetry(() => correctDocument(claims, results, settings, signal), opts),
      ]);
      if (signal.aborted) return;
      const failed = [consistency, corrections].find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined;
      patch({
        stage: 'done',
        pausedUntil: null,
        finishedAt: Date.now(),
        contradictions: consistency.status === 'fulfilled' ? consistency.value : [],
        corrections: corrections.status === 'fulfilled' ? corrections.value : [],
        reviewError: failed ? (failed.reason as Error).message : null,
      });
    },
    [settings],
  );

  const run = useCallback(
    async (file: File) => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const signal = ctrl.signal;
      setState({ ...initial, stage: 'reading', filename: file.name, startedAt: Date.now() });

      try {
        // 1. Read the PDF in the browser.
        if (file.size > MAX_FILE_MB * 1024 * 1024) throw new Error(`Please upload a PDF under ${MAX_FILE_MB} MB.`);
        const bytes = await file.arrayBuffer();
        const fileBytes = bytes.slice(0); // pdf.js takes ownership of `bytes`
        const doc = await openPdf(bytes);
        const layouts = await readLayouts(doc);
        const pages = toPageTexts(layouts).filter((p) => p.text);
        if (!pages.length) throw new Error('No selectable text found. Scanned/image-only PDFs are not supported yet.');
        patch({ doc, fileBytes, layouts, stage: 'extracting' });

        // 2. Extract claims (waiting out rate limits).
        const claims = await withRetry(() => extractClaims(pages, settings, signal), {
          signal, onWait: (sec) => pause(sec),
        });
        resume();
        if (signal.aborted) return;
        if (!claims.length) {
          patch({ claims, stage: 'done', finishedAt: Date.now() });
          return;
        }
        patch({
          claims,
          stage: 'verifying',
          status: Object.fromEntries(claims.map((c) => [c.id, 'queued' as ClaimStatus])),
        });

        // 3. Verify every claim.
        const results = await verifyAll(claims, signal);
        if (signal.aborted) return;

        // 4. Review.
        await review(claims, Object.values(results), signal);
      } catch (err) {
        if (signal.aborted) return;
        const msg = err instanceof ApiError || err instanceof Error ? err.message : 'Something went wrong.';
        patch({ stage: 'error', pausedUntil: null, error: msg });
      }
    },
    [settings, verifyAll, review],
  );

  /** Re-check only the claims that ended as "Not checked", then refresh the review. */
  const recheckFailed = useCallback(async () => {
    const failed = state.claims.filter((c) => state.results[c.id]?.verdict === 'Error');
    if (!failed.length) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    patch((s) => ({
      stage: 'verifying',
      finishedAt: null,
      status: { ...s.status, ...Object.fromEntries(failed.map((c) => [c.id, 'queued' as ClaimStatus])) },
    }));
    const fresh = await verifyAll(failed, ctrl.signal);
    if (ctrl.signal.aborted) return;
    const all = { ...state.results, ...fresh };
    await review(state.claims, Object.values(all), ctrl.signal);
  }, [state.claims, state.results, verifyAll, review]);

  const highlights: Map<number, Highlight> = useMemo(
    () => buildHighlights(state.claims, state.layouts),
    [state.claims, state.layouts],
  );

  const summary = useMemo(() => {
    const counts = { Verified: 0, Inaccurate: 0, False: 0, Error: 0 };
    for (const r of Object.values(state.results)) counts[r.verdict]++;
    const judged = counts.Verified + counts.Inaccurate + counts.False;
    return {
      counts,
      checked: Object.keys(state.status).filter((id) => state.status[Number(id)] === 'done').length,
      total: state.claims.length,
      trustScore: judged ? Math.round((counts.Verified / judged) * 100) : null,
    };
  }, [state.results, state.status, state.claims.length]);

  return { state, run, reset, recheckFailed, highlights, summary };
}
