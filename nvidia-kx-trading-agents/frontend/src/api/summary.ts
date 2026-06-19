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

import type { GenerateSummaryInput, SSEEventData } from '../types/api';
import { createSSEStream, type SSECallbacks } from './sse';
import apiClient from './client';
import { decodeHtmlEntities } from '../utils/htmlDecode';

export interface StepDetails {
  stepId: string;
  content?: string;
  results?: unknown[];
  citations?: string[];
}

export interface AgentEventData {
  // Known activity/source ids get bespoke styling; any other source id renders generically.
  type: string;
  title: string;
  content?: string;
  status?: 'running' | 'complete' | 'error';
  duration?: string;      // e.g., "1.2s", "350ms"
  recordCount?: number;   // Number of records/docs processed
}

// Parse the leading metadata tag from a source answer and strip it from the content.
// Handles: "[1.2s, 5 docs]", "[4m 22s, complete]", "[350ms]" — duration is the part before
// the comma; a record count is parsed only when the remainder contains a number.
function parseMetadata(content: string): { duration?: string; recordCount?: number; cleanContent: string } {
  const metaMatch = content.match(/^\[([^,\]]+)(?:,\s*([^\]]*))?\]/);
  if (metaMatch) {
    const duration = metaMatch[1].trim();
    const rest = (metaMatch[2] || '').trim();
    const countMatch = rest.match(/(\d+)/);
    const recordCount = countMatch ? parseInt(countMatch[1], 10) : undefined;
    const cleanContent = content.replace(/^\[[^\]]*\]\n?/, '').trim();
    return { duration, recordCount, cleanContent };
  }
  return { cleanContent: content };
}

export interface SummaryGenerationCallbacks {
  onProgress: (step: string, content?: string) => void;
  onStepDetails: (details: StepDetails) => void;
  onAgentEvent: (event: AgentEventData) => void;
  onStreamContent: (content: string) => void;
  onReport: (report: string, citations?: string) => void;
  onError: (error: Error) => void;
  onComplete: () => void;
}

export async function generateSummary(
  input: GenerateSummaryInput,
  callbacks: SummaryGenerationCallbacks
): Promise<AbortController> {
  const url = apiClient.getStreamUrl('/generate_summary/stream');

  let lastStep = '';
  let hasResearchResults = false;
  let hasSummary = false;
  let hasReflection = false;
  let hasFinalReport = false;
  let summaryUpdateCount = 0;

  const sseCallbacks: SSECallbacks = {
    onMessage: (data: SSEEventData) => {
      if (data.intermediate_step) {
        try {
          const state = JSON.parse(data.intermediate_step);

          // Detect step based on state changes
          // Backend emits: web_research_results, running_summary, reflect_on_summary, final_report, finalized_summary
          let currentStep = lastStep || 'starting';

          // Parse agent activity events (decode HTML entities in all content)
          if (state.relevancy_checker) {
            const content = decodeHtmlEntities(String(state.relevancy_checker));
            if (content.includes('Starting relevancy')) {
              callbacks.onAgentEvent({ type: 'relevancy', title: 'Checking answer relevancy', status: 'running' });
            } else if (content.includes('Relevancy score')) {
              callbacks.onAgentEvent({ type: 'relevancy', title: 'Relevancy check complete', content, status: 'complete' });
            }
          }

          if (state.kdb_answer) {
            const rawContent = decodeHtmlEntities(String(state.kdb_answer));
            const { duration, recordCount, cleanContent } = parseMetadata(rawContent);
            const title = duration
              ? `KDB-X query (${duration}${recordCount ? `, ${recordCount} records` : ''})`
              : 'KDB-X query result';
            callbacks.onAgentEvent({
              type: 'kdb',
              title,
              content: cleanContent,
              status: 'complete',
              duration,
              recordCount
            });
          }

          if (state.rag_answer) {
            const rawContent = decodeHtmlEntities(String(state.rag_answer));
            if (rawContent.includes('Performing RAG')) {
              callbacks.onAgentEvent({ type: 'rag', title: 'Searching documents', status: 'running' });
            } else if (rawContent.length > 50) {
              const { duration, recordCount, cleanContent } = parseMetadata(rawContent);
              const title = duration
                ? `Document search (${duration}${recordCount ? `, ${recordCount} docs` : ''})`
                : 'Document search complete';
              callbacks.onAgentEvent({
                type: 'rag',
                title,
                content: cleanContent,
                status: 'complete',
                duration,
                recordCount
              });
            }
          }

          if (state.web_answer) {
            const rawContent = decodeHtmlEntities(String(state.web_answer));
            if (rawContent.includes('Performing web')) {
              callbacks.onAgentEvent({ type: 'web', title: 'Searching the web', status: 'running' });
            } else if (rawContent.length > 50) {
              const { duration, recordCount, cleanContent } = parseMetadata(rawContent);
              const title = duration
                ? `Web search (${duration}${recordCount ? `, ${recordCount} results` : ''})`
                : 'Web search complete';
              callbacks.onAgentEvent({
                type: 'web',
                title,
                content: cleanContent,
                status: 'complete',
                duration,
                recordCount
              });
            }
          }

          // New source agents (fundamentals, sec_filings, market_data, news_headlines,
          // macro_economic, web_search) stream activity as `<source>_progress` (per-step
          // ReAct activity, "running") and `<source>_answer` (final result, "complete").
          // Map them generically so each source's activity shows in the agent feed.
          const DYNAMIC_SOURCES = [
            'fundamentals', 'sec_filings', 'market_data', 'news_headlines', 'macro_economic', 'web_search', 'onetick',
            'kdb_docs', 'kdb_pit',
          ] as const;
          for (const src of DYNAMIC_SOURCES) {
            const prog = state[`${src}_progress`];
            if (prog) {
              const text = decodeHtmlEntities(String(prog)).trim();
              if (text) {
                callbacks.onAgentEvent({ type: src, title: text, status: 'running' });
              }
            }
            const ans = state[`${src}_answer`];
            if (ans) {
              const rawContent = decodeHtmlEntities(String(ans));
              const { duration, recordCount, cleanContent } = parseMetadata(rawContent);
              callbacks.onAgentEvent({
                type: src,
                title: duration
                  ? `Completed in ${duration}${recordCount ? ` · ${recordCount} records` : ''}`
                  : 'Completed',
                content: cleanContent,
                status: 'complete',
                duration,
                recordCount,
              });
              if (currentStep === 'starting') currentStep = 'rag_search';
            }
          }

          // Per-query source dispatch line ("Querying fundamentals, sec_filings...").
          if (state.search_progress) {
            const text = decodeHtmlEntities(String(state.search_progress)).trim();
            if (text.startsWith('Querying')) {
              callbacks.onAgentEvent({ type: 'planning', title: text, status: 'running' });
            }
          }

          if (state.reflect_on_summary) {
            const content = decodeHtmlEntities(String(state.reflect_on_summary));
            if (content.includes('Starting reflection')) {
              callbacks.onAgentEvent({ type: 'reflection', title: 'Reflecting on report', status: 'running' });
            } else if (content.length > 100) {
              callbacks.onAgentEvent({ type: 'reflection', title: 'Identified knowledge gap', content, status: 'complete' });
            }
          }

          if (state.summarize_sources) {
            const content = decodeHtmlEntities(String(state.summarize_sources));
            if (content.includes('Starting summary')) {
              callbacks.onAgentEvent({ type: 'summary', title: 'Writing report section', status: 'running' });
            }
          }

          if (state.searching) {
            const query = state.query ? decodeHtmlEntities(String(state.query)) : '';
            callbacks.onAgentEvent({ type: 'kdb', title: `Querying KDB-X: ${query}`, status: 'running' });
            // Set step to searching when we see search activity
            if (currentStep === 'starting') {
              currentStep = 'rag_search';
            }
          }

          // Also detect search activity from kdb_answer, rag_answer, web_answer
          if ((state.kdb_answer || state.rag_answer || state.web_answer) && currentStep === 'starting') {
            currentStep = 'rag_search';
          }

          // Check for research results (includes RAG, KDB, and web search)
          // This marks the search step as having results
          if (state.web_research_results?.length > 0 && !hasResearchResults) {
            hasResearchResults = true;
            currentStep = 'rag_search';
            // Emit step details with search results
            callbacks.onStepDetails({
              stepId: 'rag_search',
              content: `Completed research with ${state.web_research_results.length} result set(s)`,
              results: state.web_research_results,
            });
          }

          // Check for running summary (writing the report)
          if (state.running_summary && state.running_summary.length > 0) {
            summaryUpdateCount++;
            if (!hasSummary) {
              hasSummary = true;
              currentStep = 'running_summary';
            }
          }

          // Check for reflection phase
          if (state.reflect_on_summary && !hasReflection) {
            hasReflection = true;
            currentStep = 'reflect_on_summary';
          }

          // Check for final report
          if (state.final_report && !hasFinalReport) {
            hasFinalReport = true;
            currentStep = 'final_report';
          }

          // Also check finalized_summary as the completion signal
          if (state.finalized_summary) {
            currentStep = 'final_report';
          }

          // Only emit progress if step changed
          if (currentStep !== lastStep && currentStep !== 'processing') {
            lastStep = currentStep;
            callbacks.onProgress(currentStep, state.running_summary || '');
          }

          // Always update streaming content if we have running_summary
          if (state.running_summary) {
            callbacks.onStreamContent(decodeHtmlEntities(state.running_summary));
          }
        } catch (e) {
          console.warn('[Summary API] Failed to parse intermediate_step:', e);
          // Don't emit progress for parse errors, just log
        }
      }

      if (data.final_report) {
        callbacks.onProgress('final_report', '');
        // Decode HTML entities in the report and citations
        callbacks.onReport(
          decodeHtmlEntities(data.final_report),
          data.citations ? decodeHtmlEntities(data.citations) : undefined
        );
      }

      if (data.error) {
        callbacks.onError(new Error(data.error));
      }
    },
    onError: callbacks.onError,
    onComplete: callbacks.onComplete,
  };

  return createSSEStream(url, input, sseCallbacks);
}
