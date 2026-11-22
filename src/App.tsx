import { AlertTriangle, RotateCcw } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Header } from './components/Header';
import { SettingsDrawer } from './components/SettingsDrawer';
import { SummaryBar } from './components/SummaryBar';
import { UploadScreen } from './components/UploadScreen';
import { Workspace } from './components/Workspace';
import { useFactCheck } from './hooks/useFactCheck';
import { getHealth } from './lib/api';
import { exportCsv, exportJson, type ReportData } from './lib/export';
import { downloadPdfReport } from './lib/pdfReport';
import type { Health, Settings } from './types';

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [settings, setSettings] = useState<Settings>({ provider: 'gemini', apiKey: '', model: 'gemini-2.5-flash', maxClaims: 20 });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { state, run, reset, recheckFailed, highlights, summary } = useFactCheck(settings);
  const lastFile = useRef<File | null>(null);

  useEffect(() => {
    getHealth().then((h) => {
      setHealth(h);
      if (h?.providers) {
        const provider = h.default_provider;
        setSettings((s) => ({ ...s, provider, model: h.providers[provider].default_model }));
      }
    });
  }, []);

  const start = (file: File) => {
    lastFile.current = file;
    if (health?.providers && !health.providers[settings.provider]?.server_key && !settings.apiKey.trim()) {
      setSettingsOpen(true);
      return;
    }
    run(file);
  };

  const report = (): ReportData => ({
    filename: state.filename,
    generatedAt: new Date().toISOString(),
    trustScore: summary.trustScore,
    claims: state.claims,
    results: state.results,
    contradictions: state.contradictions,
    corrections: state.corrections,
  });

  const keyProblem = state.error && /api key|quota|401|rate limit/i.test(state.error);

  return (
    <div className="min-h-full">
      <Header onSettings={() => setSettingsOpen(true)} onHome={reset} />

      {state.stage === 'idle' && <UploadScreen onFile={start} error={null} />}

      {state.stage === 'error' && (
        <>
          <div className="mx-auto mt-8 max-w-[1200px] px-6">
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-pen/30 bg-pen-soft px-5 py-4 text-pen" role="alert">
              <AlertTriangle className="h-5 w-5" />
              <p className="flex-1 font-semibold">{state.error}</p>
              {keyProblem && (
                <button onClick={() => setSettingsOpen(true)} className="rounded-full border border-pen px-4 py-1.5 text-sm font-semibold">
                  Use another key / provider
                </button>
              )}
              {lastFile.current && (
                <button
                  onClick={() => run(lastFile.current!)}
                  className="inline-flex items-center gap-1.5 rounded-full bg-pen px-4 py-1.5 text-sm font-semibold text-white"
                >
                  <RotateCcw className="h-4 w-4" /> Try again
                </button>
              )}
            </div>
          </div>
          <UploadScreen onFile={start} error={null} />
        </>
      )}

      {state.stage !== 'idle' && state.stage !== 'error' && (
        <>
          <SummaryBar
            filename={state.filename}
            stage={state.stage}
            counts={summary.counts}
            total={summary.total}
            checked={summary.checked}
            trustScore={summary.trustScore}
            pausedUntil={state.pausedUntil}
            onRecheck={recheckFailed}
            onCsv={() => exportCsv(report())}
            onJson={() => exportJson(report())}
            onPdf={() =>
              downloadPdfReport({
                filename: state.filename,
                fileBytes: state.fileBytes,
                layouts: state.layouts,
                highlights,
                claims: state.claims,
                results: state.results,
                corrections: state.corrections,
                contradictions: state.contradictions,
                trustScore: summary.trustScore,
                counts: summary.counts,
              })
            }
            onNew={reset}
          />
          <Workspace state={state} highlights={highlights} />
        </>
      )}

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings}
        onChange={setSettings}
        health={health}
      />
      <footer className="border-t border-rule py-6 text-center font-serif text-xs italic text-muted no-print">
        Red Pen · claims verified against the live web with {settings.provider === 'gemini' ? 'Gemini + Google Search' : 'OpenAI web search'} · always double-check before publishing
      </footer>
    </div>
  );
}
