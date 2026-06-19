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

import { clsx } from 'clsx';
import {
  AlertCircle, Bot, Brain, CheckCircle, ChevronDown, ChevronUp, DollarSign, FileText, Globe,
  LineChart, Newspaper, Search, Sparkles, TrendingUp,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  ActivityViewMode, AgentLane, NormalizedEvent, buildActivityModel, loadActivityView, saveActivityView,
  splitBursts,
} from './agentActivityModel';

// Dot palette cycling per invocation burst in the timeline (run 1, run 2, …).
const BURST_COLORS = ['bg-nvidia-green', 'bg-violet-500', 'bg-teal-500', 'bg-orange-500'];

// Known event types get bespoke icon/color/label; any other source id falls back to a
// generic look, so newly added source agents stream without further frontend changes.
export type AgentEventType =
  | 'kdb' | 'rag' | 'web' | 'relevancy' | 'reflection' | 'summary' | 'planning'
  | 'fundamentals' | 'sec_filings' | 'market_data' | 'news_headlines' | 'macro_economic' | 'web_search'
  | string;

export interface AgentEvent {
  id: string;
  timestamp: Date;
  type: AgentEventType;
  title: string;
  content?: string;
  status?: 'running' | 'complete' | 'error';
  duration?: string;      // e.g., "1.2s", "350ms"
  recordCount?: number;   // Number of records/docs processed
}

interface AgentActivityProps {
  events: AgentEvent[];
  isStreaming: boolean;
}

// Custom KX icon for KDB events - official brand colors (white text)
function KXIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <text
        x="8"
        y="12"
        textAnchor="middle"
        fill="currentColor"
        fontFamily="Arial, sans-serif"
        fontWeight="bold"
        fontSize="9"
      >
        KX
      </text>
    </svg>
  );
}

const eventIcons: Record<string, typeof Bot> = {
  kdb: KXIcon as unknown as typeof Bot,
  rag: Search,
  web: Globe,
  relevancy: CheckCircle,
  reflection: Brain,
  summary: Sparkles,
  planning: Bot,
  fundamentals: DollarSign,
  sec_filings: FileText,
  market_data: TrendingUp,
  news_headlines: Newspaper,
  macro_economic: LineChart,
  web_search: Globe,
  kdb_docs: KXIcon as unknown as typeof Bot,
  kdb_pit: KXIcon as unknown as typeof Bot,
};

// CSS keyframes for the view animations. The codebase already inlines tiny <style>
// blocks for one-off animations (see ReportProgress), so we follow the same pattern.
const ACTIVITY_KEYFRAMES = `
@keyframes aa-slidein { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:none; } }
.aa-slidein { animation: aa-slidein .45s ease; }
@keyframes aa-flow { to { background-position: 0 16px; } }
.aa-flow-y { width:2px; height:26px; background:repeating-linear-gradient(180deg, #2563EB 0 4px, transparent 4px 8px); background-size:100% 16px; }
.aa-flow-y.aa-flowing { animation: aa-flow 1s linear infinite; }
@keyframes aa-flowx { to { background-position: 10px 0; } }
.aa-beam { position:absolute; left:50%; top:50%; height:2px; transform-origin:left center; background:repeating-linear-gradient(90deg, #2563EB 0 5px, transparent 5px 10px); opacity:.45; }
.aa-beam.aa-flowing { animation: aa-flowx 1s linear infinite; }
@keyframes aa-spin { to { transform: translate(-50%,-50%) rotate(360deg); } }
.aa-ring { animation: aa-spin 40s linear infinite; }
@keyframes aa-pop { from { transform:translate(-50%,-50%) scale(0); } to { transform:translate(-50%,-50%) scale(1); } }
.aa-pop { animation: aa-pop .35s ease; }
`;

// Pulsing status dot: running = blue (accent) pulse, done = green, error = red.
function StatusDot({ status }: { status: 'running' | 'done' | 'error' | 'pending' }) {
  return (
    <span
      className={clsx(
        'inline-block w-2 h-2 rounded-full flex-shrink-0',
        status === 'error' ? 'bg-red-500'
          : status === 'running' ? 'bg-nvidia-green animate-pulse'
          : status === 'pending' ? 'bg-nvidia-gray-500'
          : 'bg-green-500'
      )}
      aria-hidden
    />
  );
}

function statusBadge(status: 'pending' | 'running' | 'done' | 'error', duration?: string, recordCount?: number) {
  if (status === 'running') {
    return (
      <span className="flex items-center gap-1.5 text-xs text-nvidia-green">
        <span className="w-1.5 h-1.5 bg-nvidia-green rounded-full animate-pulse" />running
      </span>
    );
  }
  if (status === 'done') {
    return (
      <span className="flex items-center gap-1 text-xs text-nvidia-gray-400">
        <CheckCircle className="w-3.5 h-3.5 text-green-600" />
        {duration ? `${duration}${recordCount ? ` · ${recordCount} records` : ''}` : 'done'}
      </span>
    );
  }
  if (status === 'error') {
    return (
      <span className="flex items-center gap-1 text-xs text-red-600">
        <AlertCircle className="w-3.5 h-3.5" />failed
      </span>
    );
  }
  return <span className="text-xs text-nvidia-gray-500">pending</span>;
}

function laneDoneSummary(lane: AgentLane): string {
  if (lane.status === 'error') return 'Failed';
  // An agent can be invoked several times in one run (one per routed query,
  // plus reflection re-queries) — say so instead of implying a single run.
  const bursts = splitBursts(lane.events);
  const last = bursts[bursts.length - 1];
  const runsPrefix = bursts.length > 1 ? `${bursts.length} runs` : '';

  // No completion event at all means the agent streamed activity but never
  // delivered an answer (timeout / empty result) — say that, don't imply success.
  const completedAtAll = lane.events.some((e) => e.status === 'complete');
  if (!completedAtAll) {
    return [runsPrefix, 'no result returned'].filter(Boolean).join(' · ');
  }

  // Not every agent stamps a parsable "[duration]" on its completion event —
  // fall back to the burst's own first→last timestamps.
  const lastDuration = lane.duration ?? burstElapsed(last);
  const parts = runsPrefix
    ? [`${runsPrefix}${lastDuration ? ` · last ${lastDuration}` : ''}`]
    : [`Done${lastDuration ? ` in ${lastDuration}` : ''}`];
  if (lane.recordCount) parts.push(`${lane.recordCount} records`);
  return parts.join(' · ');
}

/** Wall-clock span of a burst from its event timestamps; '' when unknowable. */
function burstElapsed(burst?: { start: number; end: number }): string {
  if (!burst || !burst.start || !burst.end || burst.end <= burst.start) return '';
  return formatElapsed(burst.end - burst.start);
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function AgentActivity({ events, isStreaming }: AgentActivityProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [view, setView] = useState<ActivityViewMode>(() => loadActivityView());
  // Grid cards are collapsed by default; this tracks the ones the user opened.
  const [openCards, setOpenCards] = useState<Set<string>>(new Set());
  const [openEvents, setOpenEvents] = useState<Set<string>>(new Set());
  const [synthOpen, setSynthOpen] = useState(false);
  // Timeline dot tooltip — rendered position:fixed at the viewport level so it can
  // never be clipped by the panel border / overflow (dots at the timeline edges).
  const [tip, setTip] = useState<{ x: number; y: number; head?: string; text: string; time?: string } | null>(null);

  // Width of the panel body, used by the radial view to lay out satellites and to
  // auto-fall back to the grid when there isn't enough room.
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [bodyWidth, setBodyWidth] = useState(1024);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setBodyWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isExpanded]);

  // Keep the timeline's "now" edge moving while streaming.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    if (!isStreaming || view !== 'timeline' || !isExpanded) return;
    const id = setInterval(() => setNowTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [isStreaming, view, isExpanded]);

  const model = useMemo(() => buildActivityModel(events, isStreaming), [events, isStreaming]);

  if (events.length === 0 && !isStreaming) {
    return null;
  }

  const changeView = (v: ActivityViewMode) => {
    setView(v);
    saveActivityView(v);
  };

  const toggleCard = (type: string) => {
    setOpenCards((prev) => {
      const next = new Set(prev);
      next.has(type) ? next.delete(type) : next.add(type);
      return next;
    });
  };

  const toggleEvent = (id: string) => {
    setOpenEvents((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  // ---- shared: per-event rows (used in expanded grid cards + synthesis node) ----
  const renderEventList = (evs: NormalizedEvent[]) => (
    <div className="space-y-0.5">
      {evs.map((ev) => {
        const isOpen = openEvents.has(ev.id);
        const hasContent = !!ev.content;
        return (
          <div key={ev.id} className="border-t border-dashed border-nvidia-gray-700 aa-slidein">
            <button
              onClick={() => hasContent && toggleEvent(ev.id)}
              disabled={!hasContent}
              aria-expanded={hasContent ? isOpen : undefined}
              className={clsx(
                'w-full flex items-start gap-2 px-1 py-1 rounded text-left transition-colors',
                hasContent ? 'hover:bg-nvidia-gray-800/60 cursor-pointer' : 'cursor-default'
              )}
            >
              <span className="flex-shrink-0 mt-1.5">
                <span className={clsx(
                  'block w-1.5 h-1.5 rounded-full',
                  ev.status === 'error' ? 'bg-red-400'
                    : ev.status === 'complete' ? 'bg-green-500'
                    : ev.status === 'running' ? 'bg-nvidia-green animate-pulse'
                    : 'bg-nvidia-gray-500'
                )} />
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs text-nvidia-gray-200 truncate">{ev.text}</p>
                {ev.timeLabel && <span className="text-[10px] text-nvidia-gray-500">{ev.timeLabel}</span>}
              </div>
              {hasContent && (
                <span className={clsx('flex-shrink-0 mt-0.5', isOpen ? 'text-nvidia-green' : 'text-nvidia-gray-500')}>
                  {isOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                </span>
              )}
            </button>
            {isOpen && hasContent && (
              <div className="pl-4 pr-1 pb-1.5">
                <div className="bg-nvidia-gray-900/70 rounded-lg border border-nvidia-gray-700 overflow-hidden">
                  <div className="px-2.5 py-1.5 border-b border-nvidia-gray-700 flex items-center justify-between">
                    <span className="text-[10px] font-medium text-nvidia-gray-400">Result Details</span>
                    <span className="text-[10px] text-nvidia-gray-500">{ev.content?.length?.toLocaleString()} chars</span>
                  </div>
                  <pre className="text-[11px] text-nvidia-gray-300 whitespace-pre-wrap p-2.5 max-h-[300px] overflow-y-auto font-mono leading-relaxed">
                    {ev.content}
                  </pre>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );

  // ---- shared: the fan-in spine (synthesis -> final report) below the grid ----
  const renderSpine = () => (
    <div className="flex flex-col items-center mt-3">
      <div className={clsx('aa-flow-y', isStreaming ? 'aa-flowing' : 'opacity-30')} aria-hidden />
      <div className="w-full sm:w-[20rem] rounded-lg border border-nvidia-green/30 bg-nvidia-green/5 p-3">
        <button
          onClick={() => model.synthEvents.length > 0 && setSynthOpen((o) => !o)}
          disabled={model.synthEvents.length === 0}
          aria-expanded={model.synthEvents.length > 0 ? synthOpen : undefined}
          className="w-full flex items-center gap-2 text-left disabled:cursor-default"
        >
          <span className="flex-shrink-0 text-nvidia-green"><Sparkles className="w-4 h-4" /></span>
          <span className="text-sm font-semibold text-nvidia-gray-50">Research Synthesis</span>
          <span className="ml-auto flex items-center gap-2">
            {statusBadge(model.synthStatus)}
            {model.synthEvents.length > 0 && (
              synthOpen
                ? <ChevronUp className="w-3.5 h-3.5 text-nvidia-gray-500" />
                : <ChevronDown className="w-3.5 h-3.5 text-nvidia-gray-500" />
            )}
          </span>
        </button>
        {model.synthEvents.length > 0 && synthOpen && (
          <div className="mt-2 max-h-60 overflow-y-auto">{renderEventList(model.synthEvents)}</div>
        )}
      </div>
      <div className={clsx('aa-flow-y', isStreaming ? 'aa-flowing' : 'opacity-30')} aria-hidden />
      <div className={clsx(
        'w-full sm:w-[20rem] rounded-lg border p-3 flex items-center gap-2',
        model.reportStatus === 'done' ? 'border-nvidia-green/50 bg-nvidia-green/5' : 'border-nvidia-gray-700 bg-nvidia-gray-900/40'
      )}>
        <span className="flex-shrink-0 text-nvidia-green"><FileText className="w-4 h-4" /></span>
        <span className="text-sm font-semibold text-nvidia-gray-50">Final Report</span>
        <span className="ml-auto">{statusBadge(model.reportStatus)}</span>
      </div>
    </div>
  );

  // ============================ A: GRID ============================
  const renderGrid = () => (
    <div>
      {model.agents.length === 0 ? (
        <div className="text-center text-nvidia-gray-500 text-sm py-2">
          {isStreaming ? 'Dispatching research to sources…' : 'No source activity.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {model.agents.map((lane) => {
            const Icon = eventIcons[lane.type] ?? Bot;
            const open = openCards.has(lane.type);
            return (
              <div
                key={lane.type}
                className={clsx(
                  'rounded-xl border bg-nvidia-gray-900/40 overflow-hidden transition-shadow hover:shadow-md',
                  lane.status === 'running' ? 'border-nvidia-green/40'
                    : lane.status === 'error' ? 'border-red-300'
                    : 'border-nvidia-gray-700'
                )}
              >
                <button
                  onClick={() => toggleCard(lane.type)}
                  aria-expanded={open}
                  className="w-full text-left p-3 hover:bg-nvidia-gray-800/60 transition-colors"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={clsx(
                      'w-6 h-6 rounded-lg bg-nvidia-green/10 flex items-center justify-center flex-shrink-0',
                      lane.colorClass
                    )}>
                      <Icon className="w-3.5 h-3.5" />
                    </span>
                    <span className="text-[13px] font-semibold text-nvidia-gray-50 truncate">{lane.label}</span>
                    <span className="ml-auto flex items-center gap-1.5 flex-shrink-0">
                      <StatusDot status={lane.status} />
                      {open ? <ChevronUp className="w-3.5 h-3.5 text-nvidia-gray-500" /> : <ChevronDown className="w-3.5 h-3.5 text-nvidia-gray-500" />}
                    </span>
                  </div>
                  <div className="mt-1.5">
                    <span className="inline-block bg-nvidia-green/10 text-nvidia-green border border-nvidia-green/30 rounded-full px-2 py-px text-[11px] font-semibold">
                      {lane.events.length} {lane.events.length === 1 ? 'event' : 'events'}
                    </span>
                  </div>
                  {/* Latest-event ticker: re-keyed by event id so each new event fade-slides in. */}
                  <p
                    key={lane.status === 'running' ? lane.latest?.id : `${lane.type}-done`}
                    className="aa-slidein mt-2 text-[11.5px] text-nvidia-gray-400 truncate"
                  >
                    {lane.status === 'running' ? (lane.latest?.text ?? '…') : laneDoneSummary(lane)}
                  </p>
                </button>
                {/* Expanded event list (smooth max-height transition). */}
                <div
                  className="transition-[max-height] duration-300 ease-in-out overflow-hidden"
                  style={{ maxHeight: open ? '16rem' : 0 }}
                  aria-hidden={!open}
                >
                  <div className="px-3 pb-3 max-h-64 overflow-y-auto">
                    {renderEventList(lane.events)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {renderSpine()}
    </div>
  );

  // ============================ B: TIMELINE ============================
  const renderTimeline = () => {
    const minTime = model.minTime || Date.now();
    const maxTime = Math.max(isStreaming ? Date.now() : (model.maxTime || minTime), minTime + 1000);
    const range = maxTime - minTime;
    const pos = (t: number) => `${Math.min(98, Math.max(1, ((t - minTime) / range) * 100))}%`;

    const lanes: Array<{ key: string; label: string; status: 'running' | 'done' | 'error' | 'pending'; events: NormalizedEvent[] }> = [
      ...model.agents.map((l) => ({ key: l.type, label: l.label, status: l.status as 'running' | 'done' | 'error', events: l.events })),
      ...(model.synthEvents.length > 0
        ? [{ key: '__synthesis__', label: 'Synthesis', status: model.synthStatus, events: model.synthEvents }]
        : []),
    ];

    if (lanes.length === 0) {
      return (
        <div className="text-center text-nvidia-gray-500 text-sm py-4">
          {isStreaming ? 'Dispatching research to sources…' : 'No source activity.'}
        </div>
      );
    }

    return (
      <div>
        <div className="relative">
          {lanes.map((lane) => (
            <div
              key={lane.key}
              className="grid grid-cols-[150px_1fr] items-center gap-2.5 py-2 border-b border-nvidia-gray-700 last:border-b-0"
            >
              <div className="flex items-center gap-2 text-[13px] font-semibold text-nvidia-gray-100 min-w-0">
                <StatusDot status={lane.status} />
                <span className="truncate">{lane.label}</span>
              </div>
              <div className={clsx(
                'relative h-6 rounded-md',
                lane.status === 'running'
                  ? 'bg-gradient-to-r from-nvidia-green/10 to-transparent'
                  : 'bg-nvidia-gray-900/60'
              )}>
                {(() => {
                  // Each burst = one invocation of the agent (one routed query /
                  // reflection re-query). Color dots per burst so multiple runs
                  // in the same lane are visually distinct.
                  const bursts = splitBursts(lane.events);
                  return bursts.flatMap((burst) => {
                    const burstColor = BURST_COLORS[burst.index % BURST_COLORS.length];
                    const runInfo = bursts.length > 1 ? `Run ${burst.index + 1}/${bursts.length}` : '';
                    const took = burst.duration ?? burstElapsed(burst);
                    const extent = [
                      burst.descriptor,
                      took && `took ${took}`,
                      typeof burst.recordCount === 'number' && `${burst.recordCount} records`,
                    ].filter(Boolean).join(' · ');
                    const head = [runInfo, extent].filter(Boolean).join(' · ');
                    return burst.events.map((ev) => (
                      <span
                        key={ev.id}
                        className={clsx(
                          'aa-pop absolute top-1/2 w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white transition-transform hover:scale-150 cursor-default',
                          ev.status === 'error' ? 'bg-red-500 shadow-[0_0_0_1px_rgba(239,68,68,.4)]' : burstColor,
                          // Completion dot: stronger ring marks the end of the run.
                          ev.status === 'complete' && 'shadow-[0_0_0_2.5px_rgba(22,163,74,.45)]'
                        )}
                        style={{ left: pos(ev.time || minTime) }}
                        onMouseEnter={(e) => {
                          const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
                          setTip({ x: r.left + r.width / 2, y: r.top, head, text: ev.text, time: ev.timeLabel });
                        }}
                        onMouseLeave={() => setTip(null)}
                      />
                    ));
                  });
                })()}
              </div>
            </div>
          ))}
          {/* "Now" line at the right edge while streaming. */}
          {isStreaming && (
            <div className="absolute top-1 bottom-1 w-0.5 bg-amber-500/70 animate-pulse" style={{ right: '1.5%' }} aria-hidden />
          )}
        </div>
        <div className="flex justify-between text-[10.5px] text-nvidia-gray-500 mt-1.5 ml-[160px]">
          {[0, 0.25, 0.5, 0.75, 1].map((f, i) => (
            <span key={f}>
              {i === 4 && isStreaming ? 'now' : formatElapsed(range * f)}
            </span>
          ))}
        </div>
      </div>
    );
  };

  // ============================ C: RADIAL ============================
  const MAX_SATELLITES = 8;
  const radialTooNarrow = bodyWidth < 640 || (typeof window !== 'undefined' && window.innerWidth < 768);

  const renderRadial = () => {
    if (model.agents.length === 0) {
      return (
        <div className="text-center text-nvidia-gray-500 text-sm py-4">
          {isStreaming ? 'Dispatching research to sources…' : 'No source activity.'}
        </div>
      );
    }

    const sats = model.agents.slice(0, MAX_SATELLITES);
    const extra = model.agents.length - sats.length;
    const n = sats.length;
    const rx = Math.min(Math.max(bodyWidth / 2 - 90, 150), 280);
    const ry = 150;
    const latestSynth = model.synthEvents[model.synthEvents.length - 1];

    return (
      <div className="relative h-[420px]" role="group" aria-label="Radial agent view">
        {/* slowly rotating dashed ring */}
        <div
          className="aa-ring absolute left-1/2 top-1/2 w-[330px] h-[330px] rounded-full border-[1.5px] border-dashed border-nvidia-green/30 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
          aria-hidden
        />
        {/* beams hub -> satellites */}
        {sats.map((lane, i) => {
          const angle = ((-90 + (i * 360) / n) * Math.PI) / 180;
          const x = rx * Math.cos(angle);
          const y = ry * Math.sin(angle);
          const len = Math.max(0, Math.sqrt(x * x + y * y) - 48);
          const deg = (Math.atan2(y, x) * 180) / Math.PI;
          return (
            <div
              key={`beam-${lane.type}`}
              className={clsx('aa-beam pointer-events-none', lane.status === 'running' && 'aa-flowing')}
              style={{ width: `${len}px`, transform: `rotate(${deg}deg)`, opacity: lane.status === 'running' ? 0.5 : 0.25 }}
              aria-hidden
            />
          );
        })}
        {/* central synthesis hub */}
        <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-32 h-32 rounded-full bg-nvidia-green/5 border-2 border-nvidia-green/30 flex flex-col items-center justify-center gap-1 px-2 text-center">
          <Sparkles className="w-4 h-4 text-nvidia-green" aria-hidden />
          <span className="text-[13px] font-bold text-nvidia-green leading-tight">Synthesis</span>
          <span className="text-[10px] text-nvidia-gray-400 leading-tight w-24 truncate">
            {latestSynth?.text ?? (model.synthStatus === 'pending' ? 'waiting…' : '')}
          </span>
          <StatusDot status={model.synthStatus} />
        </div>
        {/* satellite agent cards */}
        {sats.map((lane, i) => {
          const Icon = eventIcons[lane.type] ?? Bot;
          const angle = ((-90 + (i * 360) / n) * Math.PI) / 180;
          const x = rx * Math.cos(angle);
          const y = ry * Math.sin(angle);
          return (
            <button
              key={lane.type}
              title={lane.latest ? `${lane.latest.text}${lane.latest.timeLabel ? ` · ${lane.latest.timeLabel}` : ''}` : lane.label}
              onClick={() => {
                // Open this agent's full log in the grid view.
                setOpenCards((prev) => new Set(prev).add(lane.type));
                changeView('grid');
              }}
              className={clsx(
                'absolute w-28 px-2 py-2 text-center rounded-xl border bg-nvidia-gray-800 transition-shadow hover:shadow-md',
                lane.status === 'running' ? 'border-nvidia-green/40' : 'border-nvidia-gray-700'
              )}
              style={{ left: `calc(50% + ${x}px)`, top: `calc(50% + ${y}px)`, transform: 'translate(-50%,-50%)' }}
            >
              <span className="flex items-center justify-center gap-1.5 text-[11.5px] font-semibold text-nvidia-gray-50">
                <span className={lane.colorClass}><Icon className="w-3.5 h-3.5" /></span>
                <span className="truncate">{lane.label}</span>
              </span>
              <span className="mt-0.5 flex items-center justify-center gap-1.5 text-[10px] text-nvidia-gray-400">
                <StatusDot status={lane.status} />
                <span className="truncate max-w-[5.5rem]">
                  {lane.status === 'running' ? (lane.latest?.text ?? '…') : laneDoneSummary(lane)}
                </span>
              </span>
            </button>
          );
        })}
        {extra > 0 && (
          <span className="absolute bottom-2 right-2 bg-nvidia-green/10 text-nvidia-green border border-nvidia-green/30 rounded-full px-2.5 py-0.5 text-[11px] font-semibold">
            +{extra} more
          </span>
        )}
      </div>
    );
  };

  const viewOptions: Array<{ id: ActivityViewMode; label: string }> = [
    { id: 'grid', label: '▦ Grid' },
    { id: 'timeline', label: '☰ Timeline' },
    { id: 'radial', label: '◎ Radial' },
  ];

  return (
    <div className="bg-nvidia-gray-800/50 rounded-xl border border-nvidia-gray-700 overflow-hidden">
      <style>{ACTIVITY_KEYFRAMES}</style>
      {/* Header: panel collapse + view toggle */}
      <div className="flex items-center gap-2 pr-4">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          aria-expanded={isExpanded}
          className="flex-1 min-w-0 flex items-center gap-3 p-4 text-left hover:bg-nvidia-gray-800/50 transition-colors"
        >
          <div className="relative flex-shrink-0">
            <Bot className="w-5 h-5 text-nvidia-green" />
            {isStreaming && (
              <span className="absolute -top-1 -right-1 w-2 h-2 bg-nvidia-green rounded-full animate-pulse" />
            )}
          </div>
          <span className="font-medium text-nvidia-gray-50">Agents Activities</span>
          <span className="text-sm text-nvidia-gray-400 truncate">
            ({model.agents.length} {model.agents.length === 1 ? 'source' : 'sources'} → report, {events.length} events)
          </span>
          <span className="ml-auto flex-shrink-0">
            {isExpanded ? (
              <ChevronUp className="w-5 h-5 text-nvidia-gray-400" />
            ) : (
              <ChevronDown className="w-5 h-5 text-nvidia-gray-400" />
            )}
          </span>
        </button>
        <div
          role="group"
          aria-label="Activity view"
          className="flex items-center gap-0.5 bg-nvidia-gray-900/70 border border-nvidia-gray-700 rounded-lg p-0.5 flex-shrink-0"
        >
          {viewOptions.map((opt) => (
            <button
              key={opt.id}
              onClick={() => changeView(opt.id)}
              aria-pressed={view === opt.id}
              className={clsx(
                'px-2 py-1 rounded-md text-xs font-medium transition-colors whitespace-nowrap',
                view === opt.id
                  ? 'bg-nvidia-gray-800 text-nvidia-green shadow-sm'
                  : 'text-nvidia-gray-400 hover:text-nvidia-gray-200'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {isExpanded && (
        <div ref={bodyRef} className="border-t border-nvidia-gray-700 p-4 max-h-[34rem] overflow-y-auto">
          {view === 'grid' && renderGrid()}
          {view === 'timeline' && renderTimeline()}
          {/* Viewport-level tooltip for timeline dots: position:fixed + z-50 means it
              renders above everything and is never clipped by the panel border. */}
          {view === 'timeline' && tip && (
            <div
              className="pointer-events-none fixed z-50 w-max max-w-[280px] rounded-lg bg-slate-900 text-white text-[11px] leading-snug px-2.5 py-1.5 shadow-xl"
              style={{
                left: Math.min(Math.max(tip.x, 150), (typeof window !== 'undefined' ? window.innerWidth : 1200) - 150),
                top: tip.y - 10,
                transform: 'translate(-50%, -100%)',
              }}
              role="tooltip"
            >
              {tip.head && <span className="block font-semibold text-amber-300">{tip.head}</span>}
              <span className="block">{tip.text}</span>
              {tip.time && <span className="block text-slate-400">{tip.time}</span>}
            </div>
          )}
          {view === 'radial' && (
            radialTooNarrow ? (
              <div>
                <p className="text-[11px] text-nvidia-gray-500 italic mb-2">
                  Radial view needs a wider screen — showing grid.
                </p>
                {renderGrid()}
              </div>
            ) : (
              renderRadial()
            )
          )}
        </div>
      )}
    </div>
  );
}
