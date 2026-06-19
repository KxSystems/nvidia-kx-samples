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

import type { ArtifactQAInput, ArtifactQAOutput } from '../types/api';
import apiClient from './client';
import { createSSEStream } from './sse';

export async function askArtifactQuestion(input: ArtifactQAInput): Promise<ArtifactQAOutput> {
  return apiClient.post<ArtifactQAOutput>('/artifact_qa', input);
}

export interface ArtifactQAStreamCallbacks {
  /** New tokens of the assistant reply (delta chunks). */
  onDelta: (text: string) => void;
  /** Final message: complete cleaned reply + (possibly) updated artifact. */
  onFinal: (output: ArtifactQAOutput) => void;
  onError: (error: Error) => void;
  onComplete: () => void;
}

/** Streaming Q&A over /artifact_qa/stream — tokens render as they arrive. */
export async function askArtifactQuestionStream(
  input: ArtifactQAInput,
  callbacks: ArtifactQAStreamCallbacks
): Promise<AbortController> {
  const url = apiClient.getStreamUrl('/artifact_qa/stream');
  return createSSEStream(url, input, {
    onMessage: (data) => {
      // Each SSE message is a serialized ArtifactQAOutput (possibly nested under
      // `value` depending on the NAT response helper).
      const raw = data as Record<string, unknown>;
      const out = (typeof raw.assistant_reply === 'string' ? raw : raw.value) as ArtifactQAOutput | undefined;
      if (!out || typeof out.assistant_reply !== 'string') return;
      if (out.delta) {
        callbacks.onDelta(out.assistant_reply);
      } else {
        callbacks.onFinal(out);
      }
    },
    onError: callbacks.onError,
    onComplete: callbacks.onComplete,
  });
}

export async function rewriteArtifact(
  artifact: string,
  instructions: string,
  ragCollection: string,
  useInternet: boolean = false
): Promise<ArtifactQAOutput> {
  const input: ArtifactQAInput = {
    artifact,
    question: instructions,
    rewrite_mode: 'entire',
    use_internet: useInternet,
    rag_collection: ragCollection,
  };
  return apiClient.post<ArtifactQAOutput>('/artifact_qa', input);
}
