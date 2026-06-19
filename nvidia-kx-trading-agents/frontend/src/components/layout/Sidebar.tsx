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
import { CandlestickChart, Database, Globe, Globe2, X, Check, FileText, ListChecks, Target, TrendingUp, Building2, Newspaper, Landmark } from 'lucide-react';

// Label + icon for each dynamic source-agent key (shown in the sidebar Data Sources list).
const DYNAMIC_META: Record<string, { label: string; icon: React.ComponentType<{ className?: string }> }> = {
  onetick: { label: 'OneTick Cloud', icon: CandlestickChart },
  web_search: { label: 'Deep Web Research', icon: Globe2 },
  market_data: { label: 'Market Data', icon: TrendingUp },
  news_headlines: { label: 'News Headlines', icon: Newspaper },
  fundamentals: { label: 'Fundamentals', icon: Building2 },
  sec_filings: { label: 'SEC Filings', icon: FileText },
  macro_economic: { label: 'Macro (FRED)', icon: Landmark },
  kdb_docs: { label: 'Documents (KDB-X)', icon: FileText },
  kdb_pit: { label: 'Point-in-Time (KDB-X)', icon: CandlestickChart },
};
import { useWorkflowStore } from '../../store/workflowStore';
import { useUIStore } from '../../store/uiStore';

// KX Logo icon component - official brand colors (white text)
function KXIcon({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <text
        x="12"
        y="17"
        textAnchor="middle"
        fill="currentColor"
        fontFamily="Arial, sans-serif"
        fontWeight="bold"
        fontSize="11"
      >
        KX
      </text>
    </svg>
  );
}

export function Sidebar() {
  const {
    sources,
    dynamicSources,
    selectedCollections,
    stage,
    topic,
    reportOrganization,
    queries,
    isStreaming,
    report
  } = useWorkflowStore();
  const { isSidebarOpen, setSidebarOpen } = useUIStore();

  // Get stage label
  const getStageLabel = () => {
    switch (stage) {
      case 'idle': return 'Getting Started';
      case 'queries': return isStreaming ? 'Generating Plan...' : 'Plan Ready';
      case 'report': return isStreaming ? 'Writing Report...' : 'Report Ready';
      case 'qa': return 'Q&A Session';
      default: return 'Unknown';
    }
  };

  // Truncate text helper
  const truncate = (text: string, maxLength: number) => {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  };

  const SourceItem = ({
    label,
    icon: Icon,
    isActive,
    detail,
    iconColor
  }: {
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    isActive: boolean;
    detail?: string;
    iconColor?: string;
  }) => (
    <div className={clsx(
      'flex items-center gap-3 p-3 rounded-lg',
      isActive ? 'bg-nvidia-green/10' : 'bg-nvidia-gray-700/50'
    )}>
      <div className={clsx(
        'w-8 h-8 rounded-lg flex items-center justify-center',
        iconColor ? iconColor : (isActive ? 'bg-nvidia-green text-white' : 'bg-nvidia-gray-600 text-nvidia-gray-400')
      )}>
        <Icon className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={clsx(
            'text-sm font-medium',
            isActive ? 'text-nvidia-gray-50' : 'text-nvidia-gray-400'
          )}>
            {label}
          </span>
          {isActive && <Check className="w-4 h-4 text-nvidia-green" />}
        </div>
        {detail && (
          <p className="text-xs text-nvidia-gray-500 truncate">{detail}</p>
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Overlay for mobile */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={clsx(
          'fixed lg:static inset-y-0 left-0 z-50 w-64 bg-nvidia-gray-800 border-r border-nvidia-gray-700 transform transition-transform duration-200 ease-in-out lg:transform-none',
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        )}
      >
        <div className="h-full flex flex-col p-4">
          <div className="flex items-center justify-between lg:hidden mb-4">
            <span className="font-semibold text-nvidia-gray-50">Agents</span>
            <button
              onClick={() => setSidebarOpen(false)}
              className="p-1 text-nvidia-gray-400 hover:text-nvidia-gray-50"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="space-y-5 overflow-y-auto flex-1">
            {/* Current Status */}
            <div>
              <h3 className="text-xs font-semibold text-nvidia-gray-400 uppercase tracking-wider mb-3">
                Status
              </h3>
              <div className={clsx(
                'flex items-center gap-2 p-3 rounded-lg',
                isStreaming ? 'bg-nvidia-green/10' : 'bg-nvidia-gray-700/50'
              )}>
                {isStreaming && (
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <style>
                      {`.sidebar_spin{transform-origin:center;animation:sidebar_rotate .75s infinite linear}@keyframes sidebar_rotate{100%{transform:rotate(360deg)}}`}
                    </style>
                    <path d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z" opacity=".25" fill="#76B900"/>
                    <path d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z" className="sidebar_spin" fill="#76B900"/>
                  </svg>
                )}
                <span className={clsx(
                  'text-sm font-medium',
                  isStreaming ? 'text-nvidia-green' : 'text-nvidia-gray-50'
                )}>
                  {getStageLabel()}
                </span>
              </div>
            </div>

            {/* Report Topic */}
            {topic && (
              <div>
                <h3 className="text-xs font-semibold text-nvidia-gray-400 uppercase tracking-wider mb-3">
                  Topic
                </h3>
                <div className="p-3 rounded-lg bg-nvidia-gray-700/50">
                  <div className="flex items-start gap-2">
                    <Target className="w-4 h-4 text-nvidia-green mt-0.5 flex-shrink-0" />
                    <p className="text-sm text-nvidia-gray-50">{truncate(topic, 80)}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Report Structure */}
            {reportOrganization && (
              <div>
                <h3 className="text-xs font-semibold text-nvidia-gray-400 uppercase tracking-wider mb-3">
                  Outline
                </h3>
                <div className="p-3 rounded-lg bg-nvidia-gray-700/50">
                  <div className="flex items-start gap-2">
                    <FileText className="w-4 h-4 text-nvidia-gray-400 mt-0.5 flex-shrink-0" />
                    <p className="text-xs text-nvidia-gray-300 whitespace-pre-wrap line-clamp-4">
                      {truncate(reportOrganization, 150)}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Research Plan */}
            {queries.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-nvidia-gray-400 uppercase tracking-wider mb-3">
                  Research Plan
                </h3>
                <div className="p-3 rounded-lg bg-nvidia-gray-700/50">
                  <div className="flex items-center gap-2">
                    <ListChecks className="w-4 h-4 text-nvidia-green flex-shrink-0" />
                    <span className="text-sm text-nvidia-gray-50">{queries.length} queries</span>
                  </div>
                </div>
              </div>
            )}

            {/* Report Status */}
            {report && (
              <div>
                <h3 className="text-xs font-semibold text-nvidia-gray-400 uppercase tracking-wider mb-3">
                  Report
                </h3>
                <div className="p-3 rounded-lg bg-nvidia-green/10">
                  <div className="flex items-center gap-2">
                    <Check className="w-4 h-4 text-nvidia-green flex-shrink-0" />
                    <span className="text-sm text-nvidia-green">Generated</span>
                  </div>
                </div>
              </div>
            )}

            {/* Active Sources - only show if any source is selected */}
            {(sources.webSearch || sources.kdbx || (sources.rag && selectedCollections.length > 0) || Object.values(dynamicSources).some(Boolean)) && (
              <div>
                <h3 className="text-xs font-semibold text-nvidia-gray-400 uppercase tracking-wider mb-3">
                  Active Agents
                </h3>
                <div className="space-y-2">
                  {sources.webSearch && (
                    <SourceItem
                      label="Web Search"
                      icon={Globe}
                      isActive={true}
                    />
                  )}
                  {sources.kdbx && (
                    <SourceItem
                      label="Time-Series (KDB-X)"
                      icon={KXIcon}
                      isActive={true}
                      detail="via MCP"
                      iconColor="bg-[#1a1d22] text-white"
                    />
                  )}
                  {sources.rag && selectedCollections.length > 0 && (
                    <SourceItem
                      label="Documents (RAG)"
                      icon={Database}
                      isActive={true}
                      detail={selectedCollections.join(', ')}
                    />
                  )}
                  {Object.entries(dynamicSources)
                    .filter(([, on]) => on)
                    .map(([name]) => (
                      <SourceItem
                        key={name}
                        label={DYNAMIC_META[name]?.label ?? name}
                        icon={DYNAMIC_META[name]?.icon ?? Globe}
                        isActive={true}
                      />
                    ))}
                </div>
              </div>
            )}
          </div>

          <div className="mt-auto pt-4 border-t border-nvidia-gray-700 space-y-2">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 bg-nvidia-green rounded flex items-center justify-center flex-shrink-0">
                <span className="text-white font-bold text-[8px]">AI</span>
              </div>
              <p className="text-xs text-nvidia-gray-500">
                NVIDIA NIMs
              </p>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 bg-[#1a1d22] rounded flex items-center justify-center flex-shrink-0">
                <span className="text-white font-bold text-[8px]">KX</span>
              </div>
              <p className="text-xs text-nvidia-gray-500">
                KDB-X
              </p>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
