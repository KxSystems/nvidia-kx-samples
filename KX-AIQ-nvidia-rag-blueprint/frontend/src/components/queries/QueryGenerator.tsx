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
import { Sparkles } from 'lucide-react';
import { Button, Textarea, Card } from '../common';
import { useWorkflowStore } from '../../store/workflowStore';
import { useQueryGeneration } from '../../hooks/useQueryGeneration';

const DEFAULT_REPORT_ORG = `Sections:
1. Executive Summary
2. Background & Context
3. Key Findings
4. Analysis
5. Conclusions & Recommendations

Audience: Business executives and technical leaders
Tone: Professional, data-driven`;

const QUERY_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

export function QueryGenerator() {
  const [numQueries, setNumQueries] = useState(3);

  const {
    topic,
    reportOrganization,
    isStreaming,
    isThinking,
    queries,
    planReady,
    setTopic,
    setReportOrganization,
  } = useWorkflowStore();

  // Hide form when plan is ready (queries generated) or when currently generating
  const showForm = !planReady && queries.length === 0 && !isThinking;

  const { generate, cancel } = useQueryGeneration();

  const handleGenerate = () => {
    if (!reportOrganization.trim()) {
      setReportOrganization(DEFAULT_REPORT_ORG);
    }
    generate(numQueries);
  };

  // When form is hidden, don't render anything - ThinkingPanel is handled by ResearchPage
  if (!showForm) {
    return null;
  }

  return (
    <Card>
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-semibold text-white mb-2">
            Report Topic
          </h2>
          <p className="text-sm text-nvidia-gray-400 mb-4">
            Enter the title or subject of your research report.
          </p>
          <Textarea
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g., Q4 2024 NVIDIA Financial Performance Analysis"
            rows={3}
            disabled={isStreaming}
          />
        </div>

        <div>
          <h2 className="text-xl font-semibold text-white mb-2">
            Report Structure
          </h2>
          <p className="text-sm text-nvidia-gray-400 mb-4">
            Define how your report should be organized. Include section names, target audience, tone, or any specific requirements.
          </p>
          <Textarea
            value={reportOrganization || DEFAULT_REPORT_ORG}
            onChange={(e) => setReportOrganization(e.target.value)}
            placeholder="e.g., Sections, audience, tone, persona..."
            rows={8}
            disabled={isStreaming}
          />
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <label className="text-sm text-nvidia-gray-300">
              Number of queries:
            </label>
            <select
              value={numQueries}
              onChange={(e) => setNumQueries(Number(e.target.value))}
              disabled={isStreaming}
              className="bg-nvidia-gray-800 border border-nvidia-gray-600 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-nvidia-green focus:border-transparent"
            >
              {QUERY_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
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
              disabled={!topic.trim()}
              leftIcon={<Sparkles className="w-4 h-4" />}
            >
              Generate Plan
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
