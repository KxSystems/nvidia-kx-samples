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
import { Check, Search, FileText, RefreshCw, Sparkles, Globe, Database, Server, X, ChevronDown, ChevronUp, PenLine } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useWorkflowStore, type StepResult } from '../../store/workflowStore';
import { useDialogA11y } from '../../hooks/useDialogA11y';

/** Collapsible live view of the report draft as the writer streams it. */
function LiveDraft({ content }: { content: string }) {
  const [open, setOpen] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Follow the writing: keep the view pinned to the bottom as content streams.
  useEffect(() => {
    if (open && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [content, open]);

  return (
    <div className="border border-nvidia-gray-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-nvidia-gray-800 hover:bg-nvidia-gray-700/60 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-nvidia-gray-200">
          <PenLine className="w-4 h-4 text-nvidia-green" />
          Live draft
          <span className="text-xs text-nvidia-gray-500 font-normal">— the report as it's being written</span>
        </span>
        {open ? <ChevronUp className="w-4 h-4 text-nvidia-gray-400" /> : <ChevronDown className="w-4 h-4 text-nvidia-gray-400" />}
      </button>
      {open && (
        <div ref={scrollRef} className="markdown-content max-h-72 overflow-y-auto scrollbar-thin px-4 py-3 bg-nvidia-gray-800/40">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

interface ReportProgressProps {
  currentStep: string;
  streamingContent?: string;
  /** Shown next to the elapsed timer while running, so cancelling is findable mid-generation. */
  onCancel?: () => void;
}

// Map step IDs to icons
const stepIcons: Record<string, typeof Search> = {
  rag_search: Database,
  kdb_search: Server,
  web_research: Globe,
  running_summary: FileText,
  reflect_on_summary: RefreshCw,
  final_report: Sparkles,
};

export function ReportProgress({ currentStep, streamingContent, onCancel }: ReportProgressProps) {
  const { reportSteps, isStreaming } = useWorkflowStore();
  const [showModal, setShowModal] = useState(false);
  const modalRef = useDialogA11y(showModal, () => setShowModal(false));
  const [selectedStepDetails, setSelectedStepDetails] = useState<StepResult | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [finalTime, setFinalTime] = useState<number | null>(null);
  const startTimeRef = useRef<number | null>(null);

  // Track elapsed time
  useEffect(() => {
    if (isStreaming) {
      // Start timing when streaming begins
      if (!startTimeRef.current) {
        startTimeRef.current = Date.now();
        setFinalTime(null); // Reset final time for new generation
      }

      const interval = setInterval(() => {
        if (startTimeRef.current) {
          setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
        }
      }, 1000);

      return () => clearInterval(interval);
    } else {
      // Streaming stopped - save final time if we were timing
      if (startTimeRef.current && elapsedSeconds > 0) {
        setFinalTime(elapsedSeconds);
      }
      startTimeRef.current = null;
    }
  }, [isStreaming, elapsedSeconds]);

  // Format elapsed time
  const formatElapsedTime = (seconds: number): string => {
    if (seconds < 60) {
      return `${seconds}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  // Use dynamic steps from store, or fallback to minimal steps if empty
  const steps: StepResult[] = reportSteps.length > 0 ? reportSteps : [
    { stepId: 'running_summary', stepName: 'Writing Report', status: 'pending' },
    { stepId: 'final_report', stepName: 'Finalizing', status: 'pending' },
  ];

  // Get current step index and label for display
  const getCurrentStepInfo = () => {
    const activeIndex = steps.findIndex(s => s.status === 'active');
    const activeStep = activeIndex >= 0 ? steps[activeIndex] : null;

    if (activeStep) {
      return {
        label: activeStep.stepName,
        stepNumber: activeIndex + 1,
        totalSteps: steps.length,
      };
    }
    if (currentStep === 'starting') {
      return { label: 'Starting...', stepNumber: 0, totalSteps: steps.length };
    }
    return { label: 'Processing...', stepNumber: 0, totalSteps: steps.length };
  };

  const stepInfo = getCurrentStepInfo();

  // Check if any step is active
  const hasActiveStep = steps.some(s => s.status === 'active') || currentStep === 'starting';

  // Handle step click to show details
  const handleStepClick = (step: StepResult) => {
    if (step.content || step.details) {
      setSelectedStepDetails(step);
      setShowModal(true);
    }
  };

  return (
    <div className="space-y-6">
      {/* Current action header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {hasActiveStep && (
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <style>
                {`.progress_spinner{transform-origin:center;animation:progress_spin .75s infinite linear}@keyframes progress_spin{100%{transform:rotate(360deg)}}`}
              </style>
              <path
                d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
                opacity=".25"
                fill="#76B900"
              />
              <path
                d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
                className="progress_spinner"
                fill="#76B900"
              />
            </svg>
          )}
          <div className="flex flex-col">
            <span className={clsx(
              'text-lg font-medium',
              hasActiveStep ? 'text-nvidia-green' : 'text-nvidia-gray-50'
            )}>
              {hasActiveStep ? stepInfo.label : 'Report Generated'}
            </span>
            {hasActiveStep && stepInfo.stepNumber > 0 && (
              <span className="text-sm text-nvidia-gray-400">
                Step {stepInfo.stepNumber} of {stepInfo.totalSteps}
              </span>
            )}
          </div>
        </div>
        {/* Elapsed time + cancel while running */}
        {hasActiveStep && (
          <div className="flex items-center gap-4">
            {elapsedSeconds > 0 && (
              <div className="text-right">
                <span className="text-sm text-nvidia-gray-400">Elapsed</span>
                <div className="text-lg font-mono text-nvidia-green">
                  {formatElapsedTime(elapsedSeconds)}
                </div>
              </div>
            )}
            {onCancel && (
              <button
                onClick={onCancel}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-nvidia-gray-400 hover:text-red-600 border border-nvidia-gray-600 hover:border-red-500/50 rounded-lg transition-colors"
                aria-label="Cancel report generation"
              >
                <X className="w-4 h-4" />
                Cancel
              </button>
            )}
          </div>
        )}
        {/* Final time when complete */}
        {!hasActiveStep && finalTime && finalTime > 0 && (
          <div className="text-right">
            <span className="text-sm text-nvidia-gray-400">Completed in</span>
            <div className="text-lg font-mono text-nvidia-green">
              {formatElapsedTime(finalTime)}
            </div>
          </div>
        )}
      </div>

      {/* Progress steps */}
      <div className="bg-nvidia-gray-800/50 rounded-xl p-4">
        <div className="flex items-start justify-center">
          {steps.map((step, index) => {
            const Icon = stepIcons[step.stepId] || FileText;
            const hasDetails = !!(step.content || step.details);
            const isClickable = hasDetails && step.status !== 'pending';

            return (
              <div key={step.stepId} className="flex items-center flex-shrink-0">
                {/* Whole step (icon + label + View) is ONE clickable button */}
                <button
                  onClick={() => isClickable && handleStepClick(step)}
                  disabled={!isClickable}
                  className={clsx(
                    'flex flex-col items-center min-w-[70px] max-w-[90px] rounded-lg p-1 transition-all',
                    isClickable && 'cursor-pointer hover:bg-nvidia-green/5',
                    !isClickable && 'cursor-default'
                  )}
                  title={hasDetails ? 'Click to view details' : step.stepName}
                >
                  <span
                    className={clsx(
                      'w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 flex-shrink-0',
                      step.status === 'completed' && 'bg-nvidia-green text-white',
                      step.status === 'active' && 'bg-nvidia-green/20 text-nvidia-green border-2 border-nvidia-green',
                      step.status === 'pending' && 'bg-nvidia-gray-700 text-nvidia-gray-500',
                      step.status === 'skipped' && 'bg-nvidia-gray-700 text-nvidia-gray-500 opacity-50',
                      isClickable && 'hover:ring-2 hover:ring-nvidia-green/50'
                    )}
                  >
                    {step.status === 'completed' ? (
                      <Check className="w-5 h-5" />
                    ) : (
                      <Icon className="w-5 h-5" />
                    )}
                  </span>
                  <span
                    className={clsx(
                      'mt-2 text-xs font-medium text-center leading-tight',
                      step.status === 'active' && 'text-nvidia-green',
                      step.status === 'completed' && 'text-nvidia-gray-300',
                      step.status === 'pending' && 'text-nvidia-gray-500',
                      step.status === 'skipped' && 'text-nvidia-gray-500'
                    )}
                  >
                    {step.stepName}
                  </span>
                  {hasDetails && step.status !== 'pending' && (
                    <span className="mt-0.5 text-[10px] text-nvidia-gray-500">
                      View
                    </span>
                  )}
                </button>
                {/* Connector line */}
                {index < steps.length - 1 && (
                  <div
                    className={clsx(
                      'h-0.5 flex-shrink-0 transition-colors duration-300 mt-[-20px]',
                      // Dynamic width based on number of steps
                      steps.length <= 4 ? 'w-12' : steps.length <= 5 ? 'w-8' : 'w-6',
                      step.status === 'completed' ? 'bg-nvidia-green' : 'bg-nvidia-gray-700'
                    )}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Live draft — the report as it is being written, rendered like the final view */}
      {streamingContent && <LiveDraft content={streamingContent} />}

      {/* Step Details Modal */}
      {showModal && selectedStepDetails && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70"
          onClick={() => setShowModal(false)}
        >
          <div
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="step-details-title"
            className="bg-nvidia-gray-900 rounded-xl border border-nvidia-gray-700 max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between p-4 border-b border-nvidia-gray-700">
              <div className="flex items-center gap-3">
                {(() => {
                  const Icon = stepIcons[selectedStepDetails.stepId] || FileText;
                  return <Icon className="w-5 h-5 text-nvidia-green" />;
                })()}
                <h3 id="step-details-title" className="text-lg font-semibold text-nvidia-gray-50">{selectedStepDetails.stepName}</h3>
              </div>
              <button
                onClick={() => setShowModal(false)}
                aria-label="Close details"
                className="p-1 rounded-lg hover:bg-nvidia-gray-800 text-nvidia-gray-400 hover:text-nvidia-gray-50 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-4 overflow-y-auto flex-1">
              {(() => {
                const stepContent = selectedStepDetails.content;
                const stepResults = selectedStepDetails.details?.results;
                const hasResults = stepResults && Array.isArray(stepResults) && stepResults.length > 0;

                return (
                  <>
                    {/* Step summary */}
                    {stepContent && (
                      <div className="mb-4 p-3 bg-nvidia-gray-800 rounded-lg">
                        <p className="text-sm text-nvidia-gray-300">{stepContent}</p>
                      </div>
                    )}

                    {/* Step results */}
                    {hasResults && (
                      <div className="space-y-3">
                        <h4 className="text-sm font-medium text-nvidia-gray-400 uppercase tracking-wide">
                          Results ({stepResults.length})
                        </h4>
                        <div className="space-y-2 max-h-96 overflow-y-auto">
                          {stepResults.map((result: unknown, idx: number) => {
                            const displayText = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
                            return (
                              <div
                                key={idx}
                                className="p-3 bg-nvidia-gray-800 rounded-lg border border-nvidia-gray-700"
                              >
                                <pre className="text-xs text-nvidia-gray-300 whitespace-pre-wrap overflow-x-auto">
                                  {displayText}
                                </pre>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* No details available */}
                    {!stepContent && !hasResults && (
                      <p className="text-sm text-nvidia-gray-500 text-center py-8">
                        No details available for this step.
                      </p>
                    )}
                  </>
                );
              })()}
            </div>

            {/* Modal Footer */}
            <div className="p-4 border-t border-nvidia-gray-700">
              <button
                onClick={() => setShowModal(false)}
                className="w-full px-4 py-2 bg-nvidia-gray-800 hover:bg-nvidia-gray-700 text-nvidia-gray-50 rounded-lg transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
