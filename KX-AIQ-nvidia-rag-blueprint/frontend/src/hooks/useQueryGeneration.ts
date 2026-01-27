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
import { generateQueries } from '../api/queries';
import { useWorkflowStore } from '../store/workflowStore';

export function useQueryGeneration() {
  const abortControllerRef = useRef<AbortController | null>(null);
  const thinkingEndedRef = useRef<boolean>(false);

  const {
    topic,
    reportOrganization,
    llmName,
    sources,
    setQueries,
    setStreaming,
    setCurrentStep,
    setError,
    setStage,
    setThinkingContent,
    appendThinkingContent,
    setIsThinking,
    setPlanReady,
  } = useWorkflowStore();

  // Helper to check if content looks like JSON
  const isJsonContent = (content: string): boolean => {
    const trimmed = content.trim();
    // Check for JSON array/object starts
    if (trimmed.startsWith('[') || trimmed.startsWith('{')) return true;
    if (trimmed.startsWith(']') || trimmed.startsWith('}')) return true;
    // Check for JSON property patterns
    if (/"query"\s*:/.test(content)) return true;
    if (/"report_section"\s*:/.test(content)) return true;
    if (/"rationale"\s*:/.test(content)) return true;
    // Check for JSON-like syntax
    if (/^\s*"[^"]+"\s*:\s*"/.test(trimmed)) return true;
    if (/^\s*},?\s*$/.test(trimmed)) return true;
    if (/^\s*],?\s*$/.test(trimmed)) return true;
    if (/^\s*\[\s*$/.test(trimmed)) return true;
    if (/^\s*{\s*$/.test(trimmed)) return true;
    return false;
  };

  // Helper to extract thinking content and filter out JSON
  const extractThinkingContent = (content: string): string | null => {
    // If thinking already ended (saw </think>), ignore all content
    if (thinkingEndedRef.current) {
      return null;
    }

    let result = content;

    // Remove <think> opening tag if present
    result = result.replace(/<think>/g, '');

    // Check if this chunk contains </think> end tag
    if (result.includes('</think>')) {
      thinkingEndedRef.current = true;
      result = result.substring(0, result.indexOf('</think>'));
    }

    // Filter out JSON content
    if (isJsonContent(result)) {
      return null;
    }

    // Filter out empty content
    if (!result || result.trim().length === 0) {
      return null;
    }

    return result;
  };

  const generate = useCallback(async (numQueries: number = 5) => {
    if (!topic.trim()) {
      setError('Please enter a research topic');
      return;
    }

    setStreaming(true);
    setError(null);
    setThinkingContent('');
    setIsThinking(true);
    setPlanReady(false);
    setCurrentStep('AI-Q is thinking...');
    setStage('queries'); // Move to queries stage to show thinking panel
    thinkingEndedRef.current = false;

    try {
      abortControllerRef.current = await generateQueries(
        {
          topic,
          report_organization: reportOrganization,
          num_queries: numQueries,
          llm_name: llmName,
          // Pass source selection so query generator knows which sources are available
          use_kdb: sources.kdbx,
          use_rag: sources.rag,
          use_web: sources.webSearch,
        },
        {
          onProgress: (step, content) => {
            if (step === 'generating_questions' && content) {
              const thinkingContent = extractThinkingContent(content);
              if (thinkingContent) {
                appendThinkingContent(thinkingContent);
              }
            }
          },
          onQueries: (queries) => {
            setQueries(queries);
            setIsThinking(false);
            setPlanReady(true);
            setCurrentStep('Plan ready for review');
          },
          onError: (error) => {
            setError(error.message);
            setStreaming(false);
            setIsThinking(false);
          },
          onComplete: () => {
            setStreaming(false);
            setIsThinking(false);
          },
        }
      );
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to generate queries');
      setStreaming(false);
    }
  }, [topic, reportOrganization, llmName, sources, setQueries, setStreaming, setCurrentStep, setError, setStage, setThinkingContent, appendThinkingContent, setIsThinking, setPlanReady]);

  const cancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setStreaming(false);
      setCurrentStep('');
      setIsThinking(false);
      setPlanReady(false);
    }
  }, [setStreaming, setCurrentStep, setIsThinking, setPlanReady]);

  return { generate, cancel };
}
