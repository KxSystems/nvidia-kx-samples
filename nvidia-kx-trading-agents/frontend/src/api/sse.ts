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

import type { SSEEventData } from '../types/api';

export interface SSECallbacks {
  onMessage: (data: SSEEventData) => void;
  onError: (error: Error) => void;
  onComplete: () => void;
}

export async function createSSEStream(
  url: string,
  body: unknown,
  callbacks: SSECallbacks
): Promise<AbortController> {
  const controller = new AbortController();

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    const processStream = async () => {
      try {
        while (true) {
          const { done, value } = await reader.read();

          if (done) {
            callbacks.onComplete();
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const jsonStr = line.slice(6).trim();
              if (jsonStr) {
                try {
                  const data = JSON.parse(jsonStr) as SSEEventData;
                  callbacks.onMessage(data);
                } catch (parseError) {
                  console.warn('Failed to parse SSE data:', jsonStr);
                }
              }
            }
          }
        }
      } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
          return;
        }
        callbacks.onError(error instanceof Error ? error : new Error(String(error)));
      }
    };

    processStream();
  } catch (error) {
    callbacks.onError(error instanceof Error ? error : new Error(String(error)));
  }

  return controller;
}

export function parseIntermediateStep(stepString: string): { step: string; content?: string } {
  try {
    return JSON.parse(stepString);
  } catch {
    return { step: 'unknown', content: stepString };
  }
}
