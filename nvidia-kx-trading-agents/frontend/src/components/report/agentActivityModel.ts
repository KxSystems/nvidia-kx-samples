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

// Shared normalization model for the Agent Activity panel views (grid / timeline / radial).
// Groups the flat AgentEvent stream into per-source "lanes" with a derived status, plus the
// synthesis-pipeline events that the source branches converge into.

import type { AgentEvent } from './AgentActivity';

export type ActivityViewMode = 'grid' | 'timeline' | 'radial';
export const ACTIVITY_VIEW_STORAGE_KEY = 'kxta.activityView';

export function loadActivityView(): ActivityViewMode {
  try {
    const v = localStorage.getItem(ACTIVITY_VIEW_STORAGE_KEY);
    if (v === 'grid' || v === 'timeline' || v === 'radial') return v;
  } catch {
    /* localStorage unavailable (SSR / privacy mode) — fall back to default */
  }
  return 'grid';
}

export function saveActivityView(view: ActivityViewMode): void {
  try {
    localStorage.setItem(ACTIVITY_VIEW_STORAGE_KEY, view);
  } catch {
    /* best-effort persistence only */
  }
}

// Source agents are the parallel branches; everything else (planning / relevancy /
// reflection / summary) belongs to the synthesis trunk.
export const SOURCE_TYPES = new Set([
  'rag', 'kdb', 'web', 'fundamentals', 'sec_filings', 'market_data', 'news_headlines', 'macro_economic', 'web_search', 'onetick',
  'kdb_docs', 'kdb_pit',
]);

// KX uses white for logo, yellow (#ffcb22) for accents only.
// -600/-700 shades for readable contrast on the light theme's white surfaces.
export const eventColors: Record<string, string> = {
  kdb: 'text-nvidia-gray-100',
  rag: 'text-blue-600',
  web: 'text-green-600',
  relevancy: 'text-yellow-600',
  reflection: 'text-orange-600',
  summary: 'text-nvidia-green',
  planning: 'text-cyan-600',
  fundamentals: 'text-emerald-600',
  sec_filings: 'text-sky-600',
  market_data: 'text-amber-600',
  news_headlines: 'text-rose-600',
  macro_economic: 'text-violet-600',
  web_search: 'text-green-600',
  onetick: 'text-sky-600',
  kdb_docs: 'text-indigo-600',
  kdb_pit: 'text-indigo-600',
};

export const eventTypeLabels: Record<string, string> = {
  kdb: 'Time-Series (KDB-X)',
  rag: 'Documents (RAG)',
  web: 'Web Search',
  relevancy: 'Relevancy Check',
  reflection: 'Reflection',
  summary: 'Summary',
  planning: 'Planning',
  fundamentals: 'Fundamentals',
  sec_filings: 'SEC Filings',
  market_data: 'Market Data',
  news_headlines: 'News',
  macro_economic: 'Macro Data',
  web_search: 'Deep Web',
  onetick: 'OneTick Cloud',
  kdb_docs: 'Documents (KDB-X)',
  kdb_pit: 'Point-in-Time (KDB-X)',
};

export function labelForType(type: string): string {
  return eventTypeLabels[type] ?? type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function colorForType(type: string): string {
  return eventColors[type] ?? 'text-cyan-600';
}

export interface NormalizedEvent {
  id: string;
  text: string;
  /** Epoch ms; 0 when the timestamp was missing/unparseable. */
  time: number;
  timeLabel: string;
  status?: 'running' | 'complete' | 'error';
  content?: string;
  duration?: string;
  recordCount?: number;
}

export type LaneStatus = 'running' | 'done' | 'error';

export interface AgentLane {
  type: string;
  label: string;
  colorClass: string;
  status: LaneStatus;
  events: NormalizedEvent[];
  latest: NormalizedEvent | null;
  duration?: string;
  recordCount?: number;
}

/** One invocation of an agent: a contiguous run of events ending at a completion. */
export interface Burst {
  index: number;
  events: NormalizedEvent[];
  start: number;
  end: number;
  /** Duration/record info from the burst's completion event, when present. */
  duration?: string;
  recordCount?: number;
  /** First activity in the burst — the best descriptor we have for what it worked on. */
  descriptor: string;
}

/**
 * Split an agent's events into invocation bursts. An agent is typically invoked
 * once per routed query (plus reflection/deepen re-queries): each invocation
 * streams progress events and ends with a completion marker. A new burst starts
 * after a completion, or after a silence gap (fallback when markers are absent).
 */
export function splitBursts(events: NormalizedEvent[], gapMs = 30_000): Burst[] {
  const bursts: Burst[] = [];
  let current: NormalizedEvent[] = [];
  let prevTime = 0;
  let prevWasComplete = false;

  const flush = () => {
    if (current.length === 0) return;
    const completed = [...current].reverse().find((e) => e.status === 'complete' || e.duration);
    bursts.push({
      index: bursts.length,
      events: current,
      start: current[0].time,
      end: current[current.length - 1].time,
      duration: completed?.duration,
      recordCount: completed?.recordCount,
      descriptor: current[0].text,
    });
    current = [];
  };

  for (const ev of events) {
    const gap = prevTime > 0 && ev.time > 0 && ev.time - prevTime > gapMs;
    if (prevWasComplete || gap) flush();
    current.push(ev);
    prevTime = ev.time || prevTime;
    prevWasComplete = ev.status === 'complete';
  }
  flush();
  return bursts;
}

export interface ActivityModel {
  agents: AgentLane[];
  synthEvents: NormalizedEvent[];
  synthStatus: 'pending' | 'running' | 'done' | 'error';
  reportStatus: 'pending' | 'running' | 'done';
  /** Time range across all events with a valid timestamp (0 when none). */
  minTime: number;
  maxTime: number;
  totalEvents: number;
}

function toMillis(ts: unknown): number {
  if (ts instanceof Date) {
    const t = ts.getTime();
    return Number.isNaN(t) ? 0 : t;
  }
  if (typeof ts === 'string' || typeof ts === 'number') {
    const t = new Date(ts).getTime();
    return Number.isNaN(t) ? 0 : t;
  }
  return 0;
}

function normalizeEvent(ev: AgentEvent, idx: number): NormalizedEvent {
  const time = toMillis(ev?.timestamp);
  return {
    id: typeof ev?.id === 'string' && ev.id ? ev.id : `aa-ev-${idx}`,
    text: typeof ev?.title === 'string' && ev.title ? ev.title : '(event)',
    time,
    timeLabel: time ? new Date(time).toLocaleTimeString() : '',
    status: ev?.status,
    content: typeof ev?.content === 'string' && ev.content.length > 0 ? ev.content : undefined,
    duration: ev?.duration,
    recordCount: ev?.recordCount,
  };
}

function laneStatus(events: NormalizedEvent[], isStreaming: boolean): LaneStatus {
  if (events.some((e) => e.status === 'error')) return 'error';
  const completed = [...events].reverse().find((e) => e.status === 'complete');
  if (completed) return 'done';
  return isStreaming ? 'running' : 'done';
}

export function buildActivityModel(events: AgentEvent[], isStreaming: boolean): ActivityModel {
  const safe = Array.isArray(events) ? events.filter((e): e is AgentEvent => !!e) : [];

  // Group into lanes keyed by source/activity type, preserving first-seen order.
  const byType = new Map<string, NormalizedEvent[]>();
  const order: string[] = [];
  safe.forEach((ev, i) => {
    const type = typeof ev.type === 'string' && ev.type ? ev.type : 'unknown';
    if (!byType.has(type)) {
      byType.set(type, []);
      order.push(type);
    }
    byType.get(type)!.push(normalizeEvent(ev, i));
  });

  const agents: AgentLane[] = [];
  const synthEvents: NormalizedEvent[] = [];
  for (const type of order) {
    const evs = byType.get(type)!;
    if (!SOURCE_TYPES.has(type)) {
      synthEvents.push(...evs);
      continue;
    }
    const completed = [...evs].reverse().find((e) => e.status === 'complete');
    const withDuration = [...evs].reverse().find((e) => e.duration);
    agents.push({
      type,
      label: labelForType(type),
      colorClass: colorForType(type),
      status: laneStatus(evs, isStreaming),
      events: evs,
      latest: evs[evs.length - 1] ?? null,
      duration: withDuration?.duration,
      recordCount: completed?.recordCount,
    });
  }

  const synthStatus: ActivityModel['synthStatus'] =
    synthEvents.length === 0 ? 'pending'
      : synthEvents.some((e) => e.status === 'error') ? 'error'
      : isStreaming ? 'running'
      : 'done';
  const reportStatus: ActivityModel['reportStatus'] =
    !isStreaming && safe.length > 0 ? 'done'
      : synthEvents.length > 0 ? 'running'
      : 'pending';

  let minTime = 0;
  let maxTime = 0;
  for (const lane of agents) {
    for (const e of lane.events) {
      if (e.time > 0) {
        if (minTime === 0 || e.time < minTime) minTime = e.time;
        if (e.time > maxTime) maxTime = e.time;
      }
    }
  }
  for (const e of synthEvents) {
    if (e.time > 0) {
      if (minTime === 0 || e.time < minTime) minTime = e.time;
      if (e.time > maxTime) maxTime = e.time;
    }
  }

  return { agents, synthEvents, synthStatus, reportStatus, minTime, maxTime, totalEvents: safe.length };
}
