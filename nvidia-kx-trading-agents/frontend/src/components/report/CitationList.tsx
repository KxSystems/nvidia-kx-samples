// SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { ChevronDown, ChevronRight, ExternalLink, FileText } from 'lucide-react';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Card } from '../common';

interface CitationListProps {
  citations: string;
}

interface SourceQuery {
  text: string;
  /** The agent's answer for this query — short preview shown inline, full text on expand. */
  answer: string;
}

interface SourceRow {
  queries: SourceQuery[];
  urls: string[];
  texts: string[];
}

/** One-line preview of an answer: whitespace collapsed, markdown noise removed. */
function shortDescription(answer: string, max = 150): string {
  const flat = answer
    .replace(/[#*_`>|-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return flat.length > max ? flat.slice(0, max).trimEnd() + '…' : flat;
}

// Best-effort agent badge from a reference URL's domain.
const DOMAIN_BADGES: Array<[RegExp, string]> = [
  [/sec\.gov/i, 'SEC Filings'],
  [/fred\.stlouisfed/i, 'Macro (FRED)'],
  [/finance\.yahoo|yahoo\.com/i, 'Market Data'],
  [/alphavantage/i, 'Market Data'],
];

function badgeFor(url: string): string | null {
  for (const [re, label] of DOMAIN_BADGES) {
    if (re.test(url)) return label;
  }
  return null;
}

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url.slice(0, 40);
  }
}

/**
 * Parse the backend's structured sources blob (`---\n**Source** N\n**Query:** ...\n
 * **Answer:** ...\nCITATION(S): ...`) into table rows, deduplicating references:
 * a URL (or citation text) only appears once; queries citing the same references
 * are merged into one row.
 */
function parseSources(citations: string): SourceRow[] | null {
  if (!/\*\*Source\*\*\s*\d+/.test(citations)) return null;

  const entries = citations.split(/\n?---\s*\n\*\*Source\*\*\s*\d+/).filter((e) => e.trim());
  const seenRefs = new Set<string>();
  const rows: SourceRow[] = [];

  for (const entry of entries) {
    const query = entry.match(/\*\*Query:\*\*\s*([^\n]+)/)?.[1]?.trim() ?? '';
    const answer = entry.match(/\*\*Answer:\*\*\s*([\s\S]*?)(?=\nCITATION(?:S)?:|$)/i)?.[1]?.trim() ?? '';
    // Reference material lives after the CITATION(S): marker; fall back to the whole entry.
    const citPart = entry.split(/CITATION(?:S)?:/i).slice(1).join('\n') || '';
    const urls = Array.from(new Set(citPart.match(/https?:\/\/[^\s)\]>"']+/g) ?? []));
    // Non-URL citation lines (e.g. KDB table/dataset descriptions).
    const texts = citPart
      .split('\n')
      .map((l) => l.replace(/https?:\/\/[^\s)\]>"']+/g, '').replace(/^[-*\d.\s]+/, '').trim())
      .filter((l) => l.length > 3);

    const freshUrls = urls.filter((u) => !seenRefs.has(u));
    const freshTexts = texts.filter((t) => !seenRefs.has(t));
    freshUrls.forEach((u) => seenRefs.add(u));
    freshTexts.forEach((t) => seenRefs.add(t));

    const sq: SourceQuery = { text: query, answer };
    if (freshUrls.length === 0 && freshTexts.length === 0) {
      // Everything this entry cites is already in the table — merge its query into
      // the row that owns those references.
      const owner = rows.find((r) => urls.some((u) => r.urls.includes(u)) || texts.some((t) => r.texts.includes(t)));
      if (owner && query && !owner.queries.some((oq) => oq.text === query)) owner.queries.push(sq);
      continue;
    }
    rows.push({ queries: query ? [sq] : [], urls: freshUrls, texts: freshTexts.slice(0, 3) });
  }
  return rows.length > 0 ? rows : null;
}

/** The references cell: badged links + non-URL citation descriptions. */
function RefsCell({ row }: { row: SourceRow }) {
  return (
    <div className="flex flex-col gap-1">
      {row.urls.map((url) => {
        const badge = badgeFor(url);
        return (
          <span key={url} className="inline-flex items-center gap-2 min-w-0">
            {badge && (
              <span className="shrink-0 px-1.5 py-0.5 rounded bg-nvidia-green/10 text-nvidia-green text-[10px] font-semibold">
                {badge}
              </span>
            )}
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 hover:underline inline-flex items-center gap-1 truncate max-w-md"
              title={url}
            >
              {domainOf(url)}
              <ExternalLink className="w-3 h-3 shrink-0" />
            </a>
          </span>
        );
      })}
      {row.texts.map((t, ti) => (
        <span key={ti} className="text-xs text-nvidia-gray-400">{t}</span>
      ))}
    </div>
  );
}

/** A query row (clickable, with a short answer preview) plus its expandable answer row. */
function SourceQueryRows({
  rowNumber,
  query,
  isOpen,
  hasAnswer,
  onToggle,
  refsCell,
}: {
  rowNumber: number | null;
  query: SourceQuery;
  isOpen: boolean;
  hasAnswer: boolean;
  onToggle: () => void;
  refsCell: React.ReactNode | null;
}) {
  return (
    <>
      <tr className={rowNumber !== null ? 'border-t first:border-t-0 border-nvidia-gray-700/50 align-top' : 'align-top'}>
        <td className="py-2.5 pr-3 text-nvidia-green font-medium">{rowNumber ?? ''}</td>
        <td className="py-2.5 pr-4 text-nvidia-gray-200">
          {hasAnswer ? (
            <button
              onClick={onToggle}
              aria-expanded={isOpen}
              className="group flex items-start gap-1.5 text-left w-full hover:text-nvidia-green transition-colors"
            >
              {isOpen ? (
                <ChevronDown className="w-4 h-4 mt-0.5 shrink-0 text-nvidia-green" />
              ) : (
                <ChevronRight className="w-4 h-4 mt-0.5 shrink-0 text-nvidia-gray-500 group-hover:text-nvidia-green" />
              )}
              <span>
                {query.text}
                {!isOpen && (
                  <span className="block text-xs text-nvidia-gray-500 font-normal mt-0.5">
                    {shortDescription(query.answer)}
                  </span>
                )}
              </span>
            </button>
          ) : (
            <p className="pl-5">{query.text}</p>
          )}
        </td>
        <td className="py-2.5 text-nvidia-gray-300">{refsCell}</td>
      </tr>
      {isOpen && hasAnswer && (
        <tr>
          <td />
          <td colSpan={2} className="pb-3 pr-2">
            <div className="markdown-content text-sm bg-nvidia-gray-800/60 border border-nvidia-gray-700 rounded-lg px-4 py-3 max-h-72 overflow-y-auto scrollbar-thin">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{query.answer}</ReactMarkdown>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

/** Sources rendered as a deduplicated table (no Card wrapper — embeddable in the report). */
export function SourcesTable({ citations, className }: { citations: string; className?: string }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpanded = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  if (!citations || !citations.trim()) {
    return null;
  }

  const rows = parseSources(citations);

  // Fallback: unstructured citations — keep the simple numbered list.
  if (!rows) {
    const lines = citations.split('\n').filter((l) => l.trim()).map((l) => l.replace(/^\d+\.\s*/, '').trim());
    if (lines.length === 0) return null;
    return (
      <div className={className}>
        <h3 className="text-lg font-semibold text-nvidia-gray-50 mb-4 flex items-center gap-2">
          <FileText className="w-5 h-5 text-nvidia-green" />
          Sources
        </h3>
        <ul className="space-y-2 text-sm text-nvidia-gray-300">
          {lines.map((line, i) => (
            <li key={i}>{i + 1}. {line}</li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className={className}>
      <h3 className="text-lg font-semibold text-nvidia-gray-50 mb-4 flex items-center gap-2">
        <FileText className="w-5 h-5 text-nvidia-green" />
        Sources
        <span className="text-xs font-normal text-nvidia-gray-500">{rows.length} unique</span>
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-nvidia-gray-500 border-b border-nvidia-gray-700">
              <th className="py-2 pr-3 w-8">#</th>
              <th className="py-2 pr-4">Research query</th>
              <th className="py-2">References</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) =>
              row.queries.length > 0 ? (
                row.queries.map((q, qi) => {
                  const key = `${i}-${qi}`;
                  const isOpen = expanded.has(key);
                  const hasAnswer = q.answer.length > 0;
                  return (
                    <SourceQueryRows
                      key={key}
                      rowNumber={qi === 0 ? i + 1 : null}
                      query={q}
                      isOpen={isOpen}
                      hasAnswer={hasAnswer}
                      onToggle={() => toggleExpanded(key)}
                      refsCell={qi === 0 ? <RefsCell row={row} /> : null}
                    />
                  );
                })
              ) : (
                <tr key={i} className="border-b border-nvidia-gray-700/50 align-top">
                  <td className="py-2.5 pr-3 text-nvidia-green font-medium">{i + 1}</td>
                  <td className="py-2.5 pr-4 text-nvidia-gray-400 italic">—</td>
                  <td className="py-2.5"><RefsCell row={row} /></td>
                </tr>
              )
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Card-wrapped standalone variant (kept for callers outside the report body). */
export function CitationList({ citations }: CitationListProps) {
  if (!citations) {
    return null;
  }
  return (
    <Card>
      <SourcesTable citations={citations} />
    </Card>
  );
}
