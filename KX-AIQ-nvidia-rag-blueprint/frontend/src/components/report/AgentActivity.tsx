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
import { Bot, ChevronDown, ChevronUp, Search, Globe, Brain, CheckCircle, Sparkles, Eye } from 'lucide-react';
import { useState } from 'react';

export interface AgentEvent {
  id: string;
  timestamp: Date;
  type: 'kdb' | 'rag' | 'web' | 'relevancy' | 'reflection' | 'summary' | 'planning';
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

const eventIcons: Record<AgentEvent['type'], typeof Bot> = {
  kdb: KXIcon as unknown as typeof Bot,
  rag: Search,
  web: Globe,
  relevancy: CheckCircle,
  reflection: Brain,
  summary: Sparkles,
  planning: Bot,
};

// KX uses white for logo, yellow (#ffcb22) for accents only
const eventColors: Record<AgentEvent['type'], string> = {
  kdb: 'text-white',
  rag: 'text-blue-400',
  web: 'text-green-400',
  relevancy: 'text-yellow-400',
  reflection: 'text-orange-400',
  summary: 'text-nvidia-green',
  planning: 'text-cyan-400',
};

const eventTypeLabels: Record<AgentEvent['type'], string> = {
  kdb: 'KDB-X',
  rag: 'Document Search',
  web: 'Web Search',
  relevancy: 'Relevancy Check',
  reflection: 'Reflection',
  summary: 'Summary',
  planning: 'Planning',
};

export function AgentActivity({ events, isStreaming }: AgentActivityProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [expandedEvents, setExpandedEvents] = useState<Set<string>>(new Set());

  const toggleEvent = (id: string) => {
    setExpandedEvents(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  if (events.length === 0 && !isStreaming) {
    return null;
  }

  return (
    <div className="bg-nvidia-gray-800/50 rounded-xl border border-nvidia-gray-700 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-nvidia-gray-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="relative">
            <Bot className="w-5 h-5 text-nvidia-green" />
            {isStreaming && (
              <span className="absolute -top-1 -right-1 w-2 h-2 bg-nvidia-green rounded-full animate-pulse" />
            )}
          </div>
          <span className="font-medium text-white">Agent Activity</span>
          <span className="text-sm text-nvidia-gray-400">({events.length} events)</span>
        </div>
        {isExpanded ? (
          <ChevronUp className="w-5 h-5 text-nvidia-gray-400" />
        ) : (
          <ChevronDown className="w-5 h-5 text-nvidia-gray-400" />
        )}
      </button>

      {/* Events list */}
      {isExpanded && (
        <div className="border-t border-nvidia-gray-700 max-h-80 overflow-y-auto">
          {events.length === 0 ? (
            <div className="p-4 text-center text-nvidia-gray-500 text-sm">
              Waiting for agent activity...
            </div>
          ) : (
            <div className="divide-y divide-nvidia-gray-700/50">
              {events.map((event) => {
                const Icon = eventIcons[event.type];
                const colorClass = eventColors[event.type];
                const typeLabel = eventTypeLabels[event.type];
                const isEventExpanded = expandedEvents.has(event.id);
                const hasContent = event.content && event.content.length > 0;

                return (
                  <div key={event.id} className="group">
                    <button
                      onClick={() => hasContent && toggleEvent(event.id)}
                      disabled={!hasContent}
                      className={clsx(
                        'w-full flex items-start gap-3 p-3 text-left transition-all',
                        hasContent && 'hover:bg-nvidia-gray-800/50 cursor-pointer',
                        !hasContent && 'cursor-default',
                        isEventExpanded && 'bg-nvidia-gray-800/30'
                      )}
                    >
                      <div className={clsx('mt-0.5 flex-shrink-0', colorClass)}>
                        <Icon className="w-4 h-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={clsx(
                            'text-xs px-1.5 py-0.5 rounded font-medium',
                            colorClass,
                            'bg-nvidia-gray-900/50'
                          )}>
                            {typeLabel}
                          </span>
                          {event.status === 'running' && (
                            <span className="flex-shrink-0 w-1.5 h-1.5 bg-nvidia-green rounded-full animate-pulse" />
                          )}
                          {event.status === 'complete' && hasContent && (
                            <span className="flex items-center gap-1 text-xs text-nvidia-gray-500">
                              <Eye className="w-3 h-3" />
                              View results
                            </span>
                          )}
                        </div>
                        <p className="text-sm text-white mt-1">
                          {event.title}
                        </p>
                        <span className="text-xs text-nvidia-gray-500">
                          {event.timestamp.toLocaleTimeString()}
                        </span>
                      </div>
                      {hasContent && (
                        <div className={clsx(
                          'flex-shrink-0 transition-colors',
                          isEventExpanded ? 'text-nvidia-green' : 'text-nvidia-gray-500 group-hover:text-nvidia-gray-300'
                        )}>
                          {isEventExpanded ? (
                            <ChevronUp className="w-5 h-5" />
                          ) : (
                            <ChevronDown className="w-5 h-5" />
                          )}
                        </div>
                      )}
                    </button>
                    {/* Expanded content */}
                    {isEventExpanded && hasContent && (
                      <div className="px-3 pb-3 pl-10 animate-in slide-in-from-top-2 duration-200">
                        <div className="bg-nvidia-gray-900/70 rounded-lg border border-nvidia-gray-700 overflow-hidden">
                          <div className="px-3 py-2 border-b border-nvidia-gray-700 flex items-center justify-between">
                            <span className="text-xs font-medium text-nvidia-gray-400">Result Details</span>
                            <span className="text-xs text-nvidia-gray-500">{event.content?.length?.toLocaleString()} chars</span>
                          </div>
                          <pre className="text-xs text-nvidia-gray-300 whitespace-pre-wrap p-3 max-h-[500px] overflow-y-auto font-mono leading-relaxed">
                            {event.content}
                          </pre>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
