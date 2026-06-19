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

import { useState } from 'react';
import { AlertCircle, Sparkles } from 'lucide-react';
import { Button, Textarea, Card, Tooltip } from '../common';
import { useWorkflowStore } from '../../store/workflowStore';
import { useQueryGeneration } from '../../hooks/useQueryGeneration';

// Decision-first trade-note structure: the call up front, evidence next, action last.
const DEFAULT_REPORT_ORG = `Sections:
1. Trade Thesis — the call up front: direction, horizon, conviction, and a one-paragraph why
2. Market Overview & Price Action
3. Technical Setup (trend, momentum, key levels)
4. Fundamentals & Valuation
5. News, Catalysts & Sentiment
6. Macro & Sector Context
7. Scenarios — bull / base / bear with trigger levels
8. Risks & Counter-thesis
9. Trade Plan — entry zone, invalidation/stop, targets, time horizon, what to monitor

Audience: Portfolio managers, traders, and analysts
Tone: Professional, data-driven, decision-oriented`;

// Trading-oriented quick-starts that pre-fill the topic field.
const STARTER_PROMPTS = [
  'NVDA technical setup with fundamentals and latest news',
  'Semiconductor sector momentum and macro backdrop',
  'AAPL earnings risk from its most recent 10-K filing',
  'Compare TSLA vs RIVN on fundamentals and sentiment',
];

// Ticker quick-picks (the data loader's default symbols, so KDB-X has data for them).
const TICKER_CHIPS = ['NVDA', 'TSLA', 'RIVN', 'AAPL', 'AMD', 'TSM', 'MSFT', 'SPY'];

// Research breadth presets. The planner treats the count as a TARGET — it adds
// queries beyond it when needed to cover every (dimension, ticker) pair.
const BREADTH_PRESETS = [
  {
    label: 'Focused',
    hint: '~3 queries — just the essentials of your topic. Fastest report.',
    value: 3,
  },
  {
    label: 'Standard',
    hint: '~5 queries — your topic plus key context (news, valuation). Balanced speed and depth.',
    value: 5,
  },
  {
    label: 'Broad',
    hint: '~8 queries — adds supporting context like macro backdrop and risk angles. Most thorough, slowest.',
    value: 8,
  },
];

export function QueryGenerator() {
  const [numQueries, setNumQueries] = useState(3);

  const {
    topic,
    tickers,
    reportOrganization,
    researchDepth,
    isStreaming,
    isThinking,
    queries,
    planReady,
    error,
    setTopic,
    setTickers,
    setReportOrganization,
    setResearchDepth,
    hasAnySourceSelected,
  } = useWorkflowStore();

  const noSources = !hasAnySourceSelected();

  // Toggle a ticker chip in the comma-separated tickers field.
  const tickerList = tickers.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean);
  const toggleTicker = (sym: string) => {
    const next = tickerList.includes(sym) ? tickerList.filter((t) => t !== sym) : [...tickerList, sym];
    setTickers(next.join(', '));
  };

  // Hide form when plan is ready (queries generated) or when currently generating
  const showForm = !planReady && queries.length === 0 && !isThinking;

  const { generate, cancel } = useQueryGeneration();

  const handleGenerate = () => {
    if (noSources) return;
    if (!reportOrganization.trim()) {
      setReportOrganization(DEFAULT_REPORT_ORG);
    }
    generate(numQueries);
  };

  // Ctrl/Cmd+Enter anywhere in the form submits.
  const handleFormKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !isStreaming && topic.trim()) {
      e.preventDefault();
      handleGenerate();
    }
  };

  // When form is hidden, don't render anything - ThinkingPanel is handled by ResearchPage
  if (!showForm) {
    return null;
  }

  return (
    <Card>
      <div className="space-y-6" onKeyDown={handleFormKeyDown}>
        {error && (
          <div className="flex items-start gap-3 p-4 bg-red-500/10 border border-red-500/30 rounded-lg" role="alert">
            <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-red-600">Plan generation failed</p>
              <p className="text-sm text-nvidia-gray-300 mt-1">{error}</p>
              <p className="text-xs text-nvidia-gray-400 mt-1">
                Your inputs are kept below — click "Generate Plan" to try again.
              </p>
            </div>
          </div>
        )}

        <div>
          <h2 className="text-xl font-semibold text-nvidia-gray-50 mb-2">
            Research Topic
          </h2>
          <p className="text-sm text-nvidia-gray-400 mb-4">
            What do you want to research or decide?
          </p>
          <Textarea
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g., NVDA technical setup with fundamentals and latest news"
            rows={3}
            disabled={isStreaming}
          />
          {/* Scope hint: surface the tickers in focus next to the topic so a
              topic↔ticker mismatch is visible before generating. The topic governs
              what's researched; tickers not named in the topic are out of scope. */}
          {tickerList.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 mt-2 text-xs">
              <span className="text-nvidia-gray-500">In focus:</span>
              {tickerList.map((sym) => {
                const inTopic = topic.toUpperCase().includes(sym);
                return (
                  <span
                    key={sym}
                    title={inTopic ? 'Named in the topic' : 'In your watchlist but not named in the topic — not researched unless the topic mentions it'}
                    className={
                      inTopic
                        ? 'font-mono px-1.5 py-0.5 rounded bg-nvidia-green/10 text-nvidia-green'
                        : 'font-mono px-1.5 py-0.5 rounded bg-nvidia-gray-700 text-nvidia-gray-400 line-through decoration-1'
                    }
                  >
                    {sym}
                  </span>
                );
              })}
              {tickerList.some((s) => !topic.toUpperCase().includes(s)) && (
                <span className="text-nvidia-gray-500">
                  — struck-through tickers aren't in the topic, so they won't be researched
                </span>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 mt-3">
            <span className="text-xs text-nvidia-gray-500">Try:</span>
            {STARTER_PROMPTS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setTopic(p)}
                disabled={isStreaming}
                className="text-xs px-3 py-1.5 rounded-full border border-nvidia-gray-700 text-nvidia-gray-300 hover:border-nvidia-green hover:text-nvidia-gray-50 transition-colors disabled:opacity-50"
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-nvidia-gray-50 mb-2">
            Ticker(s) <span className="text-sm font-normal text-nvidia-gray-400">— optional</span>
          </h2>
          <p className="text-sm text-nvidia-gray-400 mb-4">
            Scope the agents to specific symbols / a watchlist (comma-separated). Leave blank to infer from the topic.
          </p>
          <input
            type="text"
            value={tickers}
            onChange={(e) => setTickers(e.target.value)}
            placeholder="e.g., NVDA, AMD, TSM"
            disabled={isStreaming}
            className="w-full bg-nvidia-gray-800 border border-nvidia-gray-600 rounded-lg px-4 py-2 text-nvidia-gray-50 placeholder-nvidia-gray-400 focus:outline-none focus:ring-2 focus:ring-nvidia-green focus:border-transparent transition-all duration-200 disabled:opacity-50"
          />
          <div className="flex flex-wrap items-center gap-2 mt-3">
            {TICKER_CHIPS.map((sym) => {
              const active = tickerList.includes(sym);
              return (
                <button
                  key={sym}
                  type="button"
                  onClick={() => toggleTicker(sym)}
                  disabled={isStreaming}
                  aria-pressed={active}
                  className={
                    active
                      ? 'text-xs font-mono font-semibold px-3 py-1.5 rounded-full border border-nvidia-green bg-nvidia-green/10 text-nvidia-green transition-colors disabled:opacity-50'
                      : 'text-xs font-mono px-3 py-1.5 rounded-full border border-nvidia-gray-700 text-nvidia-gray-300 hover:border-nvidia-green hover:text-nvidia-gray-50 transition-colors disabled:opacity-50'
                  }
                >
                  {sym}
                </button>
              );
            })}
          </div>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-nvidia-gray-50 mb-2">
            Report Outline
          </h2>
          <p className="text-sm text-nvidia-gray-400 mb-4">
            How the final report should be organized — sections, audience, tone. The default is a decision-first trade note.
          </p>
          <Textarea
            value={reportOrganization || DEFAULT_REPORT_ORG}
            onChange={(e) => setReportOrganization(e.target.value)}
            placeholder="e.g., Sections, audience, tone, persona..."
            rows={8}
            disabled={isStreaming}
          />
        </div>

        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <Tooltip content="A target, not a hard limit — the planner adds queries when needed to cover every ticker and topic dimension.">
              <label className="text-sm text-nvidia-gray-300 cursor-help border-b border-dotted border-nvidia-gray-500">
                Research breadth:
              </label>
            </Tooltip>
            {/* no overflow-hidden here — it would clip the hover tooltips; the end
                buttons carry their own corner rounding instead */}
            <div className="flex rounded-lg border border-nvidia-gray-600" role="group" aria-label="Research breadth">
              {BREADTH_PRESETS.map((p, i) => (
                <Tooltip key={p.label} content={p.hint}>
                  <button
                    type="button"
                    onClick={() => setNumQueries(p.value)}
                    disabled={isStreaming}
                    aria-pressed={numQueries === p.value}
                    className={[
                      'px-3 py-2 text-sm',
                      i === 0 ? 'rounded-l-[7px]' : '',
                      i === BREADTH_PRESETS.length - 1 ? 'rounded-r-[7px]' : '',
                      numQueries === p.value
                        ? 'font-medium bg-nvidia-green text-white'
                        : 'text-nvidia-gray-300 bg-nvidia-gray-800 hover:text-nvidia-gray-50',
                    ].join(' ')}
                  >
                    {p.label}
                  </button>
                </Tooltip>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Tooltip content="Deep runs a second 'deepen' hop built on the first round's findings. Autonomous lets a supervisor agent pick which agents to call and when to stop (bounded).">
              <label className="text-sm text-nvidia-gray-300 cursor-help border-b border-dotted border-nvidia-gray-500">
                Research depth:
              </label>
            </Tooltip>
            <select
              value={researchDepth}
              onChange={(e) => setResearchDepth(Number(e.target.value))}
              disabled={isStreaming}
              className="bg-nvidia-gray-800 border border-nvidia-gray-600 text-nvidia-gray-50 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nvidia-green focus:border-transparent"
            >
              <option value={1}>Fast (1 pass)</option>
              <option value={2}>Deep (2 passes)</option>
              <option value={3}>Autonomous (default)</option>
            </select>
          </div>

          <div className="flex-1" />

          {isStreaming ? (
            <Button variant="secondary" onClick={cancel}>
              Cancel
            </Button>
          ) : (
            <Button
              onClick={handleGenerate}
              disabled={!topic.trim() || noSources}
              leftIcon={<Sparkles className="w-4 h-4" />}
              title={noSources ? 'Select at least one agent on the Home page first' : 'Ctrl/Cmd+Enter'}
            >
              Generate Plan
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
