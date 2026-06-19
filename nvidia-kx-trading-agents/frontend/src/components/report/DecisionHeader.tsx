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

import { TrendingUp, TrendingDown, Minus, CalendarClock, Crosshair } from 'lucide-react';
import { clsx } from 'clsx';

export interface DecisionFields {
  tickers: string;
  asOf: string;
  signal: 'Bullish' | 'Bearish' | 'Neutral';
  conviction: 'Low' | 'Medium' | 'High';
  keyLevels: string;
  catalysts: string;
}

/**
 * Parse the report's markdown Decision Header (the **Ticker(s):** / **Signal:** /
 * **Key levels:** / **Next catalysts:** block the writer emits before the first
 * `##` section). Returns the fields plus the markdown body with those lines
 * removed, or null when no recognizable header exists (render markdown as-is).
 */
export function parseDecisionHeader(content: string): { fields: DecisionFields; body: string } | null {
  const firstSection = content.search(/^##\s/m);
  const head = firstSection === -1 ? content : content.slice(0, firstSection);

  const signal = head.match(/\*\*Signal:\*\*\s*(Bullish|Bearish|Neutral)/i);
  if (!signal) return null;

  const grab = (re: RegExp) => head.match(re)?.[1]?.trim() ?? '';
  const fields: DecisionFields = {
    tickers: grab(/\*\*Ticker\(s\):\*\*\s*([^*\n—]+)/i),
    asOf: grab(/\*\*As of:\*\*\s*([^*\n]+)/i),
    signal: (signal[1][0].toUpperCase() + signal[1].slice(1).toLowerCase()) as DecisionFields['signal'],
    conviction: (grab(/\*\*Conviction:\*\*\s*(Low|Medium|High)/i) || 'Low') as DecisionFields['conviction'],
    keyLevels: grab(/\*\*Key levels:\*\*\s*([^\n]+)/i),
    catalysts: grab(/\*\*Next catalysts:\*\*\s*([^\n]+)/i),
  };

  // Drop the header lines from the body; keep anything else in the preamble.
  const cleanedHead = head
    .split('\n')
    .filter((l) => !/\*\*(Ticker\(s\)|As of|Signal|Conviction|Key levels|Next catalysts):\*\*/i.test(l))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n');
  const body = (cleanedHead + (firstSection === -1 ? '' : content.slice(firstSection))).trim();

  return { fields, body };
}

const SIGNAL_STYLES: Record<DecisionFields['signal'], { badge: string; Icon: typeof TrendingUp }> = {
  Bullish: { badge: 'bg-green-100 text-green-700 border-green-300', Icon: TrendingUp },
  Bearish: { badge: 'bg-red-100 text-red-700 border-red-300', Icon: TrendingDown },
  Neutral: { badge: 'bg-slate-100 text-slate-600 border-slate-300', Icon: Minus },
};

const CONVICTION_LEVELS: Record<DecisionFields['conviction'], number> = { Low: 1, Medium: 2, High: 3 };

const isMissing = (v: string) => !v || /insufficient data|none identified/i.test(v);

export function DecisionHeader({ fields }: { fields: DecisionFields }) {
  const { badge, Icon } = SIGNAL_STYLES[fields.signal];
  const level = CONVICTION_LEVELS[fields.conviction];
  const tickers = fields.tickers.split(',').map((t) => t.trim()).filter(Boolean);

  return (
    <div className="rounded-xl border border-nvidia-gray-700 bg-nvidia-gray-800/60 p-5 mb-6">
      {/* Row 1: tickers + as-of */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          {tickers.length > 0 ? (
            tickers.map((t) => (
              <span
                key={t}
                className="px-2.5 py-1 rounded-md bg-blue-600/10 border border-blue-600/30 text-blue-700 text-sm font-semibold font-mono"
              >
                {t}
              </span>
            ))
          ) : (
            <span className="text-sm text-nvidia-gray-400">No ticker in focus</span>
          )}
        </div>
        {fields.asOf && <span className="text-xs text-nvidia-gray-400">As of {fields.asOf}</span>}
      </div>

      {/* Row 2: signal badge + conviction meter */}
      <div className="flex items-center gap-6 mt-4 flex-wrap">
        <span
          className={clsx(
            'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm font-semibold',
            badge
          )}
        >
          <Icon className="w-4 h-4" />
          {fields.signal}
        </span>
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-nvidia-gray-400">Conviction</span>
          <div className="flex items-center gap-1" aria-label={`Conviction: ${fields.conviction}`}>
            {[1, 2, 3].map((i) => (
              <span
                key={i}
                className={clsx(
                  'w-5 h-1.5 rounded-full',
                  i <= level ? 'bg-blue-600' : 'bg-nvidia-gray-600/40'
                )}
              />
            ))}
          </div>
          <span className="text-sm font-medium text-nvidia-gray-200">{fields.conviction}</span>
        </div>
      </div>

      {/* Row 3: key levels + catalysts */}
      <div className="grid sm:grid-cols-2 gap-3 mt-4 text-sm">
        <div className="flex items-start gap-2">
          <Crosshair className="w-4 h-4 text-nvidia-gray-400 mt-0.5 shrink-0" />
          <div>
            <span className="text-xs uppercase tracking-wide text-nvidia-gray-400 block">Key levels</span>
            <span className={clsx(isMissing(fields.keyLevels) ? 'text-nvidia-gray-500 italic' : 'text-nvidia-gray-100')}>
              {fields.keyLevels || 'insufficient data'}
            </span>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <CalendarClock className="w-4 h-4 text-nvidia-gray-400 mt-0.5 shrink-0" />
          <div>
            <span className="text-xs uppercase tracking-wide text-nvidia-gray-400 block">Next catalysts</span>
            <span className={clsx(isMissing(fields.catalysts) ? 'text-nvidia-gray-500 italic' : 'text-nvidia-gray-100')}>
              {fields.catalysts || 'none identified'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
