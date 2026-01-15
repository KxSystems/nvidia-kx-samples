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

import { useCallback, useRef } from 'react';
import { generateSummary } from '../api/summary';
import { useWorkflowStore, type ActiveSources } from '../store/workflowStore';

interface GenerateOptions {
  reflectionCount?: number;
  searchWeb?: boolean;
  ragCollection?: string;
  useKdb?: boolean | null;
}

export function useReportGeneration() {
  const abortControllerRef = useRef<AbortController | null>(null);
  const lastStepRef = useRef<string>('');

  const {
    topic,
    reportOrganization,
    queries,
    collection,
    searchWeb,
    llmName,
    setReport,
    setStreaming,
    setStreamingContent,
    setCurrentStep,
    setError,
    setStage,
    initializeReportSteps,
    updateStepStatus,
    setStepContent,
    clearReportSteps,
    addAgentEvent,
    clearAgentEvents,
  } = useWorkflowStore();

  const generate = useCallback(async (options: GenerateOptions = {}) => {
    const {
      reflectionCount = 1,
      searchWeb: overrideSearchWeb,
      ragCollection: overrideCollection,
      useKdb,
    } = options;

    // Use override values if provided, otherwise fall back to store values
    const effectiveSearchWeb = overrideSearchWeb !== undefined ? overrideSearchWeb : searchWeb;
    const effectiveCollection = overrideCollection !== undefined ? overrideCollection : collection;

    if (queries.length === 0) {
      setError('No queries to generate report from');
      return;
    }

    // Initialize report steps based on active sources
    const activeSources: ActiveSources = {
      rag: !!effectiveCollection,
      webSearch: effectiveSearchWeb,
      kdb: useKdb === true,
    };

    clearReportSteps();
    clearAgentEvents();
    initializeReportSteps(activeSources);
    lastStepRef.current = '';

    setStreaming(true);
    setError(null);
    setStreamingContent('');
    setCurrentStep('starting');

    try {
      abortControllerRef.current = await generateSummary(
        {
          topic,
          report_organization: reportOrganization,
          queries,
          search_web: effectiveSearchWeb,
          rag_collection: effectiveCollection,
          reflection_count: reflectionCount,
          llm_name: llmName,
          use_kdb: useKdb,  // undefined = legacy auto-detect, true = force KDB, false = disable KDB
        },
        {
          onProgress: (step, content) => {
            // Mark previous step as completed
            if (lastStepRef.current && lastStepRef.current !== 'starting' && lastStepRef.current !== step) {
              updateStepStatus(lastStepRef.current, 'completed');
            }

            // Mark current step as active
            updateStepStatus(step, 'active', content);
            lastStepRef.current = step;

            setCurrentStep(step);
            if (content) {
              setStreamingContent(content);
            }
          },
          onStepDetails: (details) => {
            // Store step results for later viewing
            setStepContent(details.stepId, details.content || '', { results: details.results });
          },
          onAgentEvent: (event) => {
            addAgentEvent(event);
          },
          onStreamContent: (content) => {
            setStreamingContent(content);
          },
          onReport: (report, citations) => {
            // Mark all steps as completed
            if (lastStepRef.current && lastStepRef.current !== 'final_report') {
              updateStepStatus(lastStepRef.current, 'completed');
            }
            updateStepStatus('final_report', 'completed');

            setCurrentStep('final_report');
            setReport(report, citations);
            setStage('report');
          },
          onError: (error) => {
            setError(error.message);
            setStreaming(false);
          },
          onComplete: () => {
            setStreaming(false);
            setCurrentStep('');
          },
        }
      );
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to generate report');
      setStreaming(false);
    }
  }, [topic, reportOrganization, queries, collection, searchWeb, llmName, setReport, setStreaming, setStreamingContent, setCurrentStep, setError, setStage, initializeReportSteps, updateStepStatus, setStepContent, clearReportSteps, addAgentEvent, clearAgentEvents]);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setStreaming(false);
      setCurrentStep('');
    }
  }, [setStreaming, setCurrentStep]);

  return { generate, cancel };
}
