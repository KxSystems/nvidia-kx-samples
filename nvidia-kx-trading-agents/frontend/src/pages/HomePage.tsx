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

import { ArrowRight, AlertCircle } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '../components/common';
import { SourceSelector } from '../components/sources';
import { useWorkflowStore } from '../store/workflowStore';
import type { Collection } from '../types/api';

interface HomePageProps {
  collections: Collection[];
  onCollectionsChange?: () => void;
}

export function HomePage({ collections, onCollectionsChange }: HomePageProps) {
  const navigate = useNavigate();
  const { sources, dynamicSources, selectedCollections, hasAnySourceSelected } = useWorkflowStore();

  const canProceed = hasAnySourceSelected();

  const handleStart = () => {
    if (canProceed) {
      navigate('/research');
    }
  };

  // Friendly labels for the dynamic source-agent keys.
  const DYNAMIC_LABELS: Record<string, string> = {
    onetick: 'OneTick Cloud',
    web_search: 'Deep Web Research',
    market_data: 'Market Data',
    news_headlines: 'News Headlines',
    fundamentals: 'Fundamentals',
    sec_filings: 'SEC Filings',
    macro_economic: 'Macro (FRED)',
    kdb_docs: 'Documents (KDB-X)',
    kdb_pit: 'Point-in-Time (KDB-X)',
  };

  // Build summary of selected sources (legacy + dynamic source agents).
  const getSelectedSummary = () => {
    const selected: string[] = [];
    if (sources.webSearch) selected.push('Web Search');
    if (sources.kdbx) selected.push('Time-Series (KDB-X)');
    if (sources.rag && selectedCollections.length > 0) {
      selected.push(`Documents (${selectedCollections.length} collection${selectedCollections.length > 1 ? 's' : ''})`);
    }
    for (const [name, on] of Object.entries(dynamicSources)) {
      if (on) selected.push(DYNAMIC_LABELS[name] ?? name);
    }
    return selected;
  };

  const selectedSummary = getSelectedSummary();

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-nvidia-gray-50 mb-2">
          AI Trading Agents
        </h1>
        <p className="text-nvidia-gray-400">
          Multi-agent financial research over KDB+/q market data and live market intelligence — orchestrated for trading insights and decision support
        </p>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-nvidia-gray-50 mb-2">
          Select Agents
        </h2>
        <p className="text-nvidia-gray-400 mb-6">
          Choose one or more agents to research with. You can combine multiple agents for more comprehensive results.
        </p>
        <SourceSelector collections={collections} onCollectionsChange={onCollectionsChange} />
      </div>

      {/* Selection Summary */}
      {selectedSummary.length > 0 && (
        <div className="bg-nvidia-gray-800 rounded-lg p-4 border border-nvidia-gray-700">
          <p className="text-sm text-nvidia-gray-300">
            <span className="font-medium text-nvidia-green">Selected agents:</span>{' '}
            {selectedSummary.join(', ')}
          </p>
        </div>
      )}

      {/* Hint: the market/tick KDB-X agents only know the data loaded into KDB-X */}
      {(sources.kdbx || dynamicSources['kdb_pit']) && (
        <div className="flex items-center gap-3 bg-blue-50 border border-blue-300 rounded-lg p-4">
          <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0" />
          <p className="text-sm text-slate-700">
            <span className="font-medium text-slate-900">KDB-X</span> and{' '}
            <span className="font-medium text-slate-900">Point-in-Time</span> answer from market/tick
            data loaded into KDB-X. Tick tables are in-memory, so if the database restarted, reload
            them in{' '}
            <Link to="/settings" className="text-blue-700 font-medium underline hover:no-underline">
              Settings → KDB-X Data
            </Link>
            . (Documents (KDB-X) uses persistent indexed filings — no loading needed.)
          </p>
        </div>
      )}

      {/* Warning if no source selected */}
      {!canProceed && (
        <div className="flex items-center gap-3 bg-amber-50 border border-amber-300 rounded-lg p-4">
          <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0" />
          <p className="text-sm font-medium text-amber-800">
            Select at least one agent to continue. If you select Documents, choose at least one collection.
          </p>
        </div>
      )}

      <div className="flex justify-center">
        <Button
          size="lg"
          onClick={handleStart}
          disabled={!canProceed}
          rightIcon={<ArrowRight className="w-5 h-5" />}
        >
          Continue to Research
        </Button>
      </div>
    </div>
  );
}
