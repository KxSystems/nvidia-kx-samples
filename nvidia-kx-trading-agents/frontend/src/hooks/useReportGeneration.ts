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

// Module-scoped so the instance that STARTS the stream (ResearchPage) and the
// instance that owns the Cancel button (ReportGenerator) share one controller.
let activeReportAbort: AbortController | null = null;

export function useReportGeneration() {
  const lastStepRef = useRef<string>('');

  const {
    topic,
    tickers,
    reportOrganization,
    researchDepth,
    queries,
    collection,
    searchWeb,
    llmName,
    dynamicSources,
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
      activeReportAbort = await generateSummary(
        {
          topic,
          tickers,
          report_organization: reportOrganization,
          queries,
          search_web: effectiveSearchWeb,
          rag_collection: effectiveCollection,
          reflection_count: reflectionCount,
          // Depth control: 1 = Fast (single scout), 2 = Deep (multi-hop), 3 = Autonomous (supervisor-lite)
          research_hops: researchDepth === 2 ? 2 : 1,
          supervisor_mode: researchDepth === 3,
          llm_name: llmName,
          use_kdb: useKdb,  // undefined = legacy auto-detect, true = force KDB, false = disable KDB
          // Per-source flags: true iff the user enabled an available source agent.
          use_web_search: !!dynamicSources['web_search'],
          use_market_data: !!dynamicSources['market_data'],
          use_news_headlines: !!dynamicSources['news_headlines'],
          use_fundamentals: !!dynamicSources['fundamentals'],
          use_sec_filings: !!dynamicSources['sec_filings'],
          use_macro_economic: !!dynamicSources['macro_economic'],
          use_onetick: !!dynamicSources['onetick'],
          use_kdb_docs: !!dynamicSources['kdb_docs'],
          use_kdb_pit: !!dynamicSources['kdb_pit'],
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
  }, [topic, tickers, reportOrganization, researchDepth, queries, collection, searchWeb, llmName, dynamicSources, setReport, setStreaming, setStreamingContent, setCurrentStep, setError, setStage, initializeReportSteps, updateStepStatus, setStepContent, clearReportSteps, addAgentEvent, clearAgentEvents]);

  const cancel = useCallback(() => {
    if (activeReportAbort) {
      activeReportAbort.abort();
      activeReportAbort = null;
      setStreaming(false);
      setCurrentStep('');
    }
  }, [setStreaming, setCurrentStep]);

  return { generate, cancel };
}
