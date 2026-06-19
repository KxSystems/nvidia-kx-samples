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
import { askArtifactQuestionStream, rewriteArtifact } from '../api/artifactQa';
import { useWorkflowStore } from '../store/workflowStore';
import type { ChatMessage } from '../types/api';

export function useArtifactQA() {
  const [isLoading, setIsLoading] = useState(false);

  const {
    report,
    collection,
    searchWeb,
    addChatMessage,
    appendToLastChatMessage,
    setLastChatMessage,
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

    // Placeholder assistant message that fills in as tokens stream.
    addChatMessage({ role: 'assistant', content: '', timestamp: new Date() });
    let gotFinal = false;

    try {
      await askArtifactQuestionStream(
        {
          artifact: report,
          question,
          use_internet: searchWeb,
          rag_collection: collection,
        },
        {
          onDelta: (text) => appendToLastChatMessage(text),
          onFinal: (output) => {
            gotFinal = true;
            // Replace the accumulated stream with the cleaned final reply.
            setLastChatMessage(output.assistant_reply);
            if (output.updated_artifact) {
              setReport(output.updated_artifact);
            }
            setIsLoading(false);
          },
          onError: (error) => {
            setError(error.message);
            setLastChatMessage('Sorry — the answer failed to generate. Please try again.');
            setIsLoading(false);
          },
          onComplete: () => {
            if (!gotFinal) {
              // Stream ended without a final message — keep whatever streamed.
            }
            setIsLoading(false);
          },
        }
      );
    } catch (error) {
      setError(error instanceof Error ? error.message : 'Failed to get response');
      setLastChatMessage('Sorry — the answer failed to generate. Please try again.');
      setIsLoading(false);
    }
  }, [report, collection, searchWeb, addChatMessage, appendToLastChatMessage, setLastChatMessage, setReport, setError]);

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
