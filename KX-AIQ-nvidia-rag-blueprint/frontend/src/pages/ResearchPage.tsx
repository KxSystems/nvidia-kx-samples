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

import { useEffect, useRef } from 'react';
import { Check } from 'lucide-react';
import { clsx } from 'clsx';
import { QueryGenerator, QueryList, ThinkingPanel } from '../components/queries';
import { ReportGenerator } from '../components/report';
import { QAPanel } from '../components/qa';
import { useWorkflowStore } from '../store/workflowStore';
import { useReportGeneration } from '../hooks/useReportGeneration';

const steps = [
  { id: 'queries', label: 'Plan Research' },
  { id: 'report', label: 'Execute & Report' },
  { id: 'qa', label: 'Q&A' },
];

// Inline spinner styles
const spinnerStyles = `
  @keyframes plan-spinner-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
  .plan-spinner {
    width: 20px;
    height: 20px;
    border: 2px solid #76B900;
    border-top-color: transparent;
    border-radius: 50%;
    animation: plan-spinner-spin 1s linear infinite;
  }
`;

export function ResearchPage() {
  const {
    stage,
    queries,
    sources,
    selectedCollections,
    thinkingContent,
    isThinking,
    isStreaming,
    topic,
    reportOrganization,
    planReady,
    setStage,
    setPlanReady,
    setThinkingContent,
    setCollection,
    setSearchWeb,
  } = useWorkflowStore();
  const { generate: generateReport } = useReportGeneration();
  const queryListRef = useRef<HTMLDivElement>(null);

  const currentStepIndex = steps.findIndex((s) => s.id === stage);

  // Scroll to query list when plan is ready
  useEffect(() => {
    if (planReady && queries.length > 0 && queryListRef.current) {
      setTimeout(() => {
        queryListRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 100);
    }
  }, [planReady, queries.length]);

  const handleExecutePlan = () => {
    // Determine collection from selected sources
    const ragCollection = selectedCollections.length > 0 ? selectedCollections[0] : '';

    // Determine KDB flag:
    // - If KDB-X is selected in UI: force KDB (true)
    // - If KDB-X is not selected: disable KDB (false)
    // - Legacy UI (no sources object): undefined = auto-detect
    const useKdb = sources.kdbx === true ? true : false;

    // Update store for persistence (optional, for display purposes)
    setSearchWeb(sources.webSearch);
    setCollection(ragCollection);

    setStage('report');
    setPlanReady(false);
    setThinkingContent('');

    // Pass sources directly to avoid state timing issues
    generateReport({
      reflectionCount: 1,
      searchWeb: sources.webSearch,
      ragCollection: ragCollection,
      useKdb: useKdb,
    });
  };

  const handleBackToQueries = () => {
    setStage('queries');
  };

  const handleStartQA = () => {
    setStage('qa');
  };

  const handleBackToReport = () => {
    setStage('report');
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Step Indicator */}
      <div className="flex items-center justify-center gap-4">
        {steps.map((step, index) => {
          const isCompleted = index < currentStepIndex;
          const isCurrent = step.id === stage;
          const isAccessible = index <= currentStepIndex || (step.id === 'queries' && queries.length > 0);

          return (
            <div key={step.id} className="flex items-center">
              <button
                onClick={() => isAccessible && setStage(step.id as typeof stage)}
                disabled={!isAccessible}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200',
                  isCurrent && 'bg-nvidia-green/20 text-nvidia-green',
                  isCompleted && !isCurrent && 'text-nvidia-gray-300 hover:bg-nvidia-gray-800',
                  !isCompleted && !isCurrent && 'text-nvidia-gray-500',
                  isAccessible && 'cursor-pointer',
                  !isAccessible && 'cursor-not-allowed'
                )}
              >
                <div
                  className={clsx(
                    'w-6 h-6 rounded-full flex items-center justify-center text-xs font-semibold',
                    isCurrent && 'bg-nvidia-green text-black',
                    isCompleted && !isCurrent && 'bg-nvidia-gray-600 text-white',
                    !isCompleted && !isCurrent && 'bg-nvidia-gray-700 text-nvidia-gray-400'
                  )}
                >
                  {isCompleted ? <Check className="w-3 h-3" /> : index + 1}
                </div>
                <span className="text-sm font-medium hidden sm:inline">{step.label}</span>
              </button>
              {index < steps.length - 1 && (
                <div
                  className={clsx(
                    'w-8 h-0.5 mx-2',
                    index < currentStepIndex ? 'bg-nvidia-green' : 'bg-nvidia-gray-700'
                  )}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Stage Content */}
      {stage === 'idle' && <QueryGenerator />}

      {stage === 'queries' && (
        <div className="max-w-3xl mx-auto space-y-6">
          <QueryGenerator />

          {/* Show Topic & Structure summary when form is hidden */}
          {(isThinking || thinkingContent || queries.length > 0) && topic && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-medium text-nvidia-gray-400 uppercase tracking-wide mb-1">
                  Report Topic
                </h3>
                <p className="text-white">{topic}</p>
              </div>
              {reportOrganization && (
                <div>
                  <h3 className="text-sm font-medium text-nvidia-gray-400 uppercase tracking-wide mb-1">
                    Report Structure
                  </h3>
                  <pre className="text-sm text-nvidia-gray-300 whitespace-pre-wrap font-sans">
                    {reportOrganization}
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* Show ThinkingPanel when thinking or has reasoning content */}
          {(isStreaming || isThinking || thinkingContent) && (
            <ThinkingPanel
              content={thinkingContent}
              isThinking={isThinking}
              isStreaming={isStreaming}
            />
          )}
          {/* Show loading skeleton while generating queries */}
          {isStreaming && queries.length === 0 && (
            <div className="space-y-4">
              <style>{spinnerStyles}</style>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <svg
                    width="24"
                    height="24"
                    viewBox="0 0 24 24"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <style>
                      {`.plan_spinner{transform-origin:center;animation:plan_spin .75s infinite linear}@keyframes plan_spin{100%{transform:rotate(360deg)}}`}
                    </style>
                    <path
                      d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
                      opacity=".25"
                      fill="#76B900"
                    />
                    <path
                      d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
                      className="plan_spinner"
                      fill="#76B900"
                    />
                  </svg>
                  <div>
                    <h2 className="text-xl font-semibold text-white">Generating Research Plan</h2>
                    <p className="text-sm text-nvidia-gray-400 mt-1">Creating queries based on your topic...</p>
                  </div>
                </div>
              </div>
              <div className="space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="bg-nvidia-gray-800 rounded-xl border border-nvidia-gray-700 p-4 animate-pulse">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-nvidia-gray-700"></div>
                      <div className="flex-1">
                        <div className="h-4 bg-nvidia-gray-700 rounded w-3/4"></div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Show QueryList when queries are available */}
          {queries.length > 0 && (
            <div ref={queryListRef}>
              <QueryList onExecutePlan={handleExecutePlan} />
            </div>
          )}
        </div>
      )}

      {stage === 'report' && (
        <ReportGenerator
          onBack={handleBackToQueries}
          onStartQA={handleStartQA}
        />
      )}

      {stage === 'qa' && <QAPanel onBack={handleBackToReport} />}
    </div>
  );
}
