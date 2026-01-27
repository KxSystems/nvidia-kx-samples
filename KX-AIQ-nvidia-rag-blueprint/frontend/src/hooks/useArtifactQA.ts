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

import { useCallback, useState } from 'react';
import { askArtifactQuestion, rewriteArtifact } from '../api/artifactQa';
import { useWorkflowStore } from '../store/workflowStore';
import type { ChatMessage } from '../types/api';

export function useArtifactQA() {
  const [isLoading, setIsLoading] = useState(false);

  const {
    report,
    collection,
    searchWeb,
    addChatMessage,
    setReport,
    setError,
  } = useWorkflowStore();

  const ask = useCallback(async (question: string) => {
    if (!question.trim()) return;

    setIsLoading(true);
    setError(null);

    // Add user message
    const userMessage: ChatMessage = {
      role: 'user',
      content: question,
      timestamp: new Date(),
    };
    addChatMessage(userMessage);

    try {
      const response = await askArtifactQuestion({
        artifact: report,
        question,
        use_internet: searchWeb,
        rag_collection: collection,
      });

      // Add assistant response
      const assistantMessage: ChatMessage = {
        role: 'assistant',
        content: response.assistant_reply,
        timestamp: new Date(),
      };
      addChatMessage(assistantMessage);

      // Update report if rewritten
      if (response.updated_artifact) {
        setReport(response.updated_artifact);
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to get response');
    } finally {
      setIsLoading(false);
    }
  }, [report, collection, searchWeb, addChatMessage, setReport, setError]);

  const rewrite = useCallback(async (instructions: string) => {
    if (!instructions.trim()) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await rewriteArtifact(
        report,
        instructions,
        collection,
        searchWeb
      );

      if (response.updated_artifact) {
        setReport(response.updated_artifact);

        // Add messages to chat history
        addChatMessage({
          role: 'user',
          content: `Rewrite request: ${instructions}`,
          timestamp: new Date(),
        });
        addChatMessage({
          role: 'assistant',
          content: 'Report has been updated based on your instructions.',
          timestamp: new Date(),
        });
      }
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to rewrite report');
    } finally {
      setIsLoading(false);
    }
  }, [report, collection, searchWeb, addChatMessage, setReport, setError]);

  return { ask, rewrite, isLoading };
}
