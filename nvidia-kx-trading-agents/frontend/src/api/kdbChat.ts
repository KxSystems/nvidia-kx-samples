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

import { apiClient } from './client';

export interface KDBChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sqlQuery?: string;
  data?: unknown[];
  isThinking?: boolean;
  toolResults?: Array<{
    tool: string;
    purpose: string;
    success: boolean;
  }>;
}

export interface KDBChatEvent {
  type: 'thinking' | 'query' | 'result' | 'error';
  content?: string;
  sql_query?: string;
  data?: unknown[];
  message?: string;
  tool_results?: Array<{
    tool: string;
    purpose: string;
    success: boolean;
  }>;
}

export interface KDBStatus {
  connected: boolean;
  message: string;
  tables?: string[];
  mcp_endpoint?: string;
}

export interface KDBSchema {
  schema: string;
  tools: string;
  sql_guidance?: string;
}

/**
 * Send a chat message to KDB and stream the response via SSE
 */
export async function sendKDBChatMessage(
  message: string,
  onEvent: (event: KDBChatEvent) => void,
  sessionId?: string
): Promise<void> {
  const baseUrl = apiClient.baseUrl;
  const response = await fetch(`${baseUrl}/kdb/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
    },
    body: JSON.stringify({
      message,
      session_id: sessionId,
    }),
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

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Process complete events from buffer
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            onEvent(data as KDBChatEvent);
          } catch {
            console.warn('Failed to parse SSE event:', line);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Check KDB connection status
 */
export async function getKDBStatus(): Promise<KDBStatus> {
  const baseUrl = apiClient.baseUrl;
  const response = await fetch(`${baseUrl}/kdb/status`);

  if (!response.ok) {
    return {
      connected: false,
      message: `HTTP error: ${response.status}`,
    };
  }

  return response.json();
}

/**
 * Get KDB schema information
 */
export async function getKDBSchema(): Promise<KDBSchema> {
  const baseUrl = apiClient.baseUrl;
  const response = await fetch(`${baseUrl}/kdb/schema`);

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  return response.json();
}
