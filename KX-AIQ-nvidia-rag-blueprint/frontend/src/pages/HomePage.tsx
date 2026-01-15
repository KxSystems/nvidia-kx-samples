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
import { useNavigate } from 'react-router-dom';
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
  const { sources, selectedCollections, hasAnySourceSelected } = useWorkflowStore();

  const canProceed = hasAnySourceSelected();

  const handleStart = () => {
    if (canProceed) {
      navigate('/research');
    }
  };

  // Build summary of selected sources
  const getSelectedSummary = () => {
    const selected: string[] = [];
    if (sources.webSearch) selected.push('Web Search');
    if (sources.kdbx) selected.push('KDB-X');
    if (sources.rag && selectedCollections.length > 0) {
      selected.push(`RAG (${selectedCollections.length} collection${selectedCollections.length > 1 ? 's' : ''})`);
    }
    return selected;
  };

  const selectedSummary = getSelectedSummary();

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <div className="text-center">
        <h1 className="text-3xl font-bold text-white mb-2">
          AI-Q Blueprint
        </h1>
        <p className="text-nvidia-gray-400">
          Generate comprehensive research reports powered by NVIDIA NIMs
        </p>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-white mb-2">
          Select Data Sources
        </h2>
        <p className="text-nvidia-gray-400 mb-6">
          Choose one or more sources for your research. You can combine multiple sources for more comprehensive results.
        </p>
        <SourceSelector collections={collections} onCollectionsChange={onCollectionsChange} />
      </div>

      {/* Selection Summary */}
      {selectedSummary.length > 0 && (
        <div className="bg-nvidia-gray-800 rounded-lg p-4 border border-nvidia-gray-700">
          <p className="text-sm text-nvidia-gray-300">
            <span className="font-medium text-nvidia-green">Selected sources:</span>{' '}
            {selectedSummary.join(', ')}
          </p>
        </div>
      )}

      {/* Warning if no source selected */}
      {!canProceed && (
        <div className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4">
          <AlertCircle className="w-5 h-5 text-yellow-500 flex-shrink-0" />
          <p className="text-sm text-yellow-200">
            Please select at least one data source to continue. If you select RAG, choose at least one collection.
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
