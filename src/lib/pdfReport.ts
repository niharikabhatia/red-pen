/**
 * "Download PDF report": the original PDF with every claim boxed in its verdict
 * colour and numbered (§n), followed by report pages: score, counts, and every
 * claim with its verdict, real fact, explanation, evidence and sources.
 */
import { PDFDocument, StandardFonts, rgb, type PDFFont, type PDFPage, type RGB } from 'pdf-lib';
import type { Highlight } from './highlight';
import type { PageLayout } from './pdf';
import { VERDICT_ORDER } from './verdict';
import type { Claim, ClaimResult, Contradiction, Correction, Verdict } from '../types';

export interface PdfReportInput {
  filename: string;
  fileBytes: ArrayBuffer | null;
  layouts: PageLayout[];
  highlights: Map<number, Highlight>;
  claims: Claim[];
  results: Record<number, ClaimResult>;
  corrections: Correction[];
  contradictions: Contradiction[];
  trustScore: number | null;
  counts: Record<Verdict, number>;
}

const NAVY = rgb(0.043, 0.071, 0.125); // #0B1220
const INK = rgb(0.1, 0.12, 0.17);
const MUTED = rgb(0.42, 0.46, 0.53);
const RULE = rgb(0.85, 0.87, 0.9);
const COLORS: Record<Verdict, RGB> = {
  Verified: rgb(0.06, 0.6, 0.42),
  Inaccurate: rgb(0.85, 0.58, 0.02),
  False: rgb(0.86, 0.2, 0.2),
  Error: rgb(0.5, 0.53, 0.6),
};
const LABEL: Record<Verdict, string> = { Verified: 'VERIFIED', Inaccurate: 'INACCURATE', False: 'FALSE', Error: 'NOT CHECKED' };

/** Standard PDF fonts only cover WinAnsi: map typography to safe characters. */
function clean(text: string): string {
  return (text || '')
    .replace(/[‘’‛]/g, "'")
    .replace(/[“”‟]/g, '"')
    .replace(/[–—−]/g, '-')
    .replace(/…/g, '...')
    .replace(/[≈]/g, '~')
    .replace(/[≠]/g, '!=')
    .replace(/[   ]/g, ' ')
    .replace(/[^\x09\x0A\x0D\x20-\x7E¡-ÿ]/g, '');
}

function wrap(text: string, font: PDFFont, size: number, width: number): string[] {
  const lines: string[] = [];
  for (const para of clean(text).split('\n')) {
    let line = '';
    for (const word of para.split(/\s+/).filter(Boolean)) {
      const next = line ? `${line} ${word}` : word;
      if (font.widthOfTextAtSize(next, size) <= width) {
        line = next;
      } else {
        if (line) lines.push(line);
        // hard-break very long tokens (URLs)
        let w = word;
        while (font.widthOfTextAtSize(w, size) > width) {
          let cut = w.length - 1;
          while (cut > 1 && font.widthOfTextAtSize(w.slice(0, cut), size) > width) cut--;
          lines.push(w.slice(0, cut));
          w = w.slice(cut);
        }
        line = w;
      }
    }
    lines.push(line);
  }
  return lines;
}

/** Draw coloured boxes + §n labels over the original pages. */
async function markUp(out: PDFDocument, input: PdfReportInput, bold: PDFFont) {
  if (!input.fileBytes) return;
  let src: PDFDocument;
  try {
    src = await PDFDocument.load(input.fileBytes, { ignoreEncryption: true });
  } catch {
    return; // unusual PDF: still produce the report pages
  }
  const indices = input.layouts.map((l) => l.page - 1).filter((i) => i < src.getPageCount());
  const pages = await out.copyPages(src, indices);
  pages.forEach((page, idx) => {
    out.addPage(page);
    const pageNo = indices[idx] + 1;
    const { height } = page.getSize();
    for (const h of input.highlights.values()) {
      if (h.page !== pageNo) continue;
      const verdict = input.results[h.claimId]?.verdict ?? 'Error';
      const color = COLORS[verdict];
      h.rects.forEach((r, i) => {
        page.drawRectangle({
          x: r.x, y: height - r.y - r.h, width: r.w, height: r.h,
          color, opacity: 0.22, borderColor: color, borderWidth: 0.6, borderOpacity: 0.9,
        });
        if (i === 0) {
          const tag = `§${h.claimId}`;
          const tw = bold.widthOfTextAtSize(tag, 7);
          const tx = 10; // left margin, so labels never cover the text
          const ty = height - r.y - r.h / 2 - 3;
          page.drawRectangle({ x: tx - 2, y: ty - 2, width: tw + 4, height: 10, color });
          page.drawText(tag, { x: tx, y: ty, size: 7, font: bold, color: rgb(1, 1, 1) });
        }
      });
    }
  });
}

class Writer {
  page!: PDFPage;
  y = 0;
  readonly W = 595.28;
  readonly H = 841.89;
  readonly M = 50;
  constructor(private doc: PDFDocument, private font: PDFFont, private bold: PDFFont, private footer: string) {
    this.newPage();
  }
  get width() {
    return this.W - 2 * this.M;
  }
  newPage() {
    this.page = this.doc.addPage([this.W, this.H]);
    this.y = this.H - this.M;
    this.page.drawText(clean(this.footer), { x: this.M, y: 24, size: 8, font: this.font, color: MUTED });
  }
  ensure(h: number) {
    if (this.y - h < this.M) this.newPage();
  }
  text(t: string, o: { size?: number; bold?: boolean; color?: RGB; indent?: number; gap?: number } = {}) {
    const size = o.size ?? 10;
    const font = o.bold ? this.bold : this.font;
    const indent = o.indent ?? 0;
    for (const line of wrap(t, font, size, this.width - indent)) {
      this.ensure(size * 1.35);
      this.page.drawText(line, { x: this.M + indent, y: this.y - size, size, font, color: o.color ?? INK });
      this.y -= size * 1.35;
    }
    this.y -= o.gap ?? 4;
  }
  rule(gap = 10) {
    this.ensure(gap * 2);
    this.y -= gap;
    this.page.drawLine({ start: { x: this.M, y: this.y }, end: { x: this.W - this.M, y: this.y }, thickness: 0.5, color: RULE });
    this.y -= gap;
  }
}

export async function buildPdfReport(input: PdfReportInput): Promise<Uint8Array> {
  const out = await PDFDocument.create();
  const font = await out.embedFont(StandardFonts.Helvetica);
  const bold = await out.embedFont(StandardFonts.HelveticaBold);
  const serif = await out.embedFont(StandardFonts.TimesRomanBold);
  const date = new Date().toLocaleString('en-GB', { dateStyle: 'long', timeStyle: 'short' });

  // ---- Cover / summary page
  const w = new Writer(out, font, bold, `Red Pen fact-check report · ${input.filename} · ${date}`);
  w.page.drawRectangle({ x: 0, y: w.H - 150, width: w.W, height: 150, color: NAVY });
  w.page.drawText('Red Pen', { x: w.M, y: w.H - 70, size: 30, font: serif, color: rgb(0.9, 0.92, 0.95) });
  w.page.drawText('FACT-CHECK REPORT', { x: w.M, y: w.H - 95, size: 10, font: bold, color: rgb(0.97, 0.44, 0.44) });
  w.page.drawText(clean(input.filename).slice(0, 80), { x: w.M, y: w.H - 120, size: 11, font, color: rgb(0.7, 0.74, 0.8) });
  w.y = w.H - 190;

  const score = input.trustScore == null ? '-' : `${input.trustScore}%`;
  w.page.drawText(score, { x: w.M, y: w.y - 48, size: 52, font: serif, color: INK });
  w.page.drawText('of checked claims hold up', { x: w.M + serif.widthOfTextAtSize(score, 52) + 12, y: w.y - 30, size: 13, font, color: MUTED });
  w.y -= 80;
  const c = input.counts;
  const items: [Verdict, number][] = [['Verified', c.Verified], ['Inaccurate', c.Inaccurate], ['False', c.False], ['Error', c.Error]];
  let x = w.M;
  for (const [v, n] of items) {
    if (v === 'Error' && !n) continue;
    w.page.drawRectangle({ x, y: w.y - 6, width: 9, height: 9, color: COLORS[v] });
    const label = `${n} ${v === 'Error' ? 'not checked' : v.toLowerCase()}`;
    w.page.drawText(label, { x: x + 14, y: w.y - 5, size: 11, font: bold, color: INK });
    x += 14 + bold.widthOfTextAtSize(label, 11) + 22;
  }
  w.y -= 30;
  w.text(
    `Every factual claim (statistics, dates, financial and technical figures) was extracted from the document and checked against the live web on ${date}. ` +
      'Inaccurate = real topic but wrong or outdated figure; False = no credible evidence. ' +
      (input.fileBytes ? 'The pages after this report show each claim boxed in its verdict colour and numbered.' : ''),
    { size: 9.5, color: MUTED, gap: 6 },
  );

  // ---- Claims
  w.rule();
  w.text('Claims', { size: 16, bold: true, gap: 8 });
  const sorted = [...input.claims].sort((a, b) => {
    const va = input.results[a.id]?.verdict ?? 'Error';
    const vb = input.results[b.id]?.verdict ?? 'Error';
    return VERDICT_ORDER[va] - VERDICT_ORDER[vb] || a.id - b.id;
  });
  for (const claim of sorted) {
    const r = input.results[claim.id];
    const v: Verdict = r?.verdict ?? 'Error';
    w.ensure(90);
    const head = `§${claim.id}  ${LABEL[v]}`;
    w.page.drawRectangle({ x: w.M, y: w.y - 13, width: bold.widthOfTextAtSize(head, 9) + 12, height: 15, color: COLORS[v] });
    w.page.drawText(clean(head), { x: w.M + 6, y: w.y - 9, size: 9, font: bold, color: rgb(1, 1, 1) });
    const meta = [claim.category, claim.page ? `page ${claim.page}` : '', r?.confidence ? `${r.confidence}% confident` : '']
      .filter(Boolean).join(' · ');
    w.page.drawText(clean(meta), { x: w.M + bold.widthOfTextAtSize(head, 9) + 22, y: w.y - 9, size: 8.5, font, color: MUTED });
    w.y -= 22;
    w.text(claim.text, { size: 11, bold: true, gap: 3 });
    if (claim.quote && claim.quote !== claim.text) w.text(`Document says: "${claim.quote}"`, { size: 9, color: MUTED, gap: 3 });
    if (r?.correct_fact) {
      const label = v === 'Verified' ? 'Confirmed: ' : 'Real fact: ';
      w.text(label + r.correct_fact, { size: 10, bold: v !== 'Verified', color: v === 'Verified' ? INK : COLORS[v], gap: 3 });
    }
    if (r?.explanation) w.text(r.explanation, { size: 9.5, gap: 3 });
    if (r?.evidence_quote) w.text(`Evidence: "${r.evidence_quote}"`, { size: 9, color: MUTED, gap: 3 });
    for (const s of r?.sources.slice(0, 3) ?? []) {
      const name = s.title && !s.title.startsWith('http') ? s.title.split(' · ')[0] : '';
      w.text(`- ${name ? name + ': ' : ''}${s.url}`, { size: 7.5, color: MUTED, indent: 8, gap: 0 });
    }
    w.rule(8);
  }

  // ---- Contradictions + corrections
  if (input.contradictions.length) {
    w.text('Internal contradictions', { size: 16, bold: true, gap: 8 });
    for (const k of input.contradictions) {
      w.text(`§${k.claim_ids.join(' vs §')}: ${k.explanation}`, { size: 10, gap: 6 });
    }
    w.rule();
  }
  if (input.corrections.length) {
    w.text('Corrected passages', { size: 16, bold: true, gap: 8 });
    for (const k of input.corrections) {
      w.text(`§${k.claim_id}  Before: ${k.original}`, { size: 9.5, color: MUTED, gap: 2 });
      w.text(`After: ${k.corrected}`, { size: 10, bold: true, indent: 22, gap: 8 });
    }
  }

  // ---- Marked-up original pages
  await markUp(out, input, bold);

  out.setTitle(`Red Pen fact-check report: ${clean(input.filename)}`);
  out.setProducer('Red Pen');
  return out.save();
}

export async function downloadPdfReport(input: PdfReportInput) {
  const bytes = await buildPdfReport(input);
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: 'application/pdf' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `${input.filename.replace(/\.pdf$/i, '') || 'document'}-red-pen-report.pdf`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
