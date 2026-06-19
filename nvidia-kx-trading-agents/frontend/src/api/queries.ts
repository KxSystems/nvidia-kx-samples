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

import type { GenerateQueryInput, GeneratedQuery, SSEEventData } from '../types/api';
import { createSSEStream, type SSECallbacks } from './sse';
import apiClient from './client';
import { decodeHtmlEntities } from '../utils/htmlDecode';

export interface QueryGenerationCallbacks {
  onProgress: (step: string, content?: string) => void;
  onQueries: (queries: GeneratedQuery[]) => void;
  onError: (error: Error) => void;
  onComplete: () => void;
}

export async function generateQueries(
  input: GenerateQueryInput,
  callbacks: QueryGenerationCallbacks
): Promise<AbortController> {
  const url = apiClient.getStreamUrl('/generate_query/stream');

  const sseCallbacks: SSECallbacks = {
    onMessage: (data: SSEEventData) => {
      if (data.intermediate_step) {
        try {
          const step = JSON.parse(data.intermediate_step);
          // Backend sends format like {"generating_questions": "content"}
          // Extract the first key-value pair
          const keys = Object.keys(step);
          if (keys.length > 0) {
            const stepName = keys[0];
            const content = step[stepName];
            callbacks.onProgress(stepName, typeof content === 'string' ? content : JSON.stringify(content));
          }
        } catch {
          // If not JSON, treat the whole thing as content
          callbacks.onProgress('generating_questions', data.intermediate_step);
        }
      }
      if (data.queries) {
        // Decode HTML entities in query text
        const decodedQueries = data.queries.map(q => ({
          ...q,
          query: decodeHtmlEntities(q.query),
          report_section: decodeHtmlEntities(q.report_section),
          rationale: decodeHtmlEntities(q.rationale),
        }));
        callbacks.onQueries(decodedQueries);
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
