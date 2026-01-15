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

import { useCallback, useState, useRef } from 'react';
import {
  sendKDBChatMessage,
  getKDBStatus,
  type KDBChatMessage,
  type KDBChatEvent,
  type KDBStatus,
} from '../api/kdbChat';

interface UseKDBChatReturn {
  messages: KDBChatMessage[];
  isLoading: boolean;
  error: string | null;
  status: KDBStatus | null;
  sendMessage: (message: string) => Promise<void>;
  clearHistory: () => void;
  checkStatus: () => Promise<void>;
}

let messageIdCounter = 0;

function generateMessageId(): string {
  return `kdb-msg-${Date.now()}-${messageIdCounter++}`;
}

export function useKDBChat(): UseKDBChatReturn {
  const [messages, setMessages] = useState<KDBChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<KDBStatus | null>(null);
  const sessionIdRef = useRef<string>(`session-${Date.now()}`);

  const checkStatus = useCallback(async () => {
    try {
      const kdbStatus = await getKDBStatus();
      setStatus(kdbStatus);
    } catch (err) {
      setStatus({
        connected: false,
        message: err instanceof Error ? err.message : 'Failed to check status',
      });
    }
  }, []);

  const sendMessage = useCallback(async (message: string) => {
    if (!message.trim() || isLoading) return;

    setIsLoading(true);
    setError(null);

    // Add user message immediately
    const userMessage: KDBChatMessage = {
      id: generateMessageId(),
      role: 'user',
      content: message,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);

    // Add placeholder for assistant response (thinking state)
    const assistantMessageId = generateMessageId();
    const assistantMessage: KDBChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isThinking: true,
    };
    setMessages(prev => [...prev, assistantMessage]);

    try {
      let currentSqlQuery: string | undefined;
      let finalContent = '';
      let finalData: unknown[] | undefined;
      let toolResults: Array<{ tool: string; purpose: string; success: boolean }> | undefined;

      await sendKDBChatMessage(
        message,
        (event: KDBChatEvent) => {
          switch (event.type) {
            case 'thinking':
              setMessages(prev =>
                prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: event.content || 'Thinking...', isThinking: true }
                    : msg
                )
              );
              break;

            case 'query':
              currentSqlQuery = event.sql_query;
              setMessages(prev =>
                prev.map(msg =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        content: event.content || 'Executing query...',
                        sqlQuery: event.sql_query,
                        isThinking: true,
                      }
                    : msg
                )
              );
              break;

            case 'result':
              finalContent = event.content || '';
              finalData = event.data;
              toolResults = event.tool_results;
              if (event.sql_query) currentSqlQuery = event.sql_query;

              setMessages(prev =>
                prev.map(msg =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        content: finalContent,
                        sqlQuery: currentSqlQuery,
                        data: finalData,
                        toolResults,
                        isThinking: false,
                      }
                    : msg
                )
              );
              break;

            case 'error':
              setError(event.message || 'An error occurred');
              setMessages(prev =>
                prev.map(msg =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        content: event.message || 'An error occurred',
                        isThinking: false,
                      }
                    : msg
                )
              );
              break;
          }
        },
        sessionIdRef.current
      );
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to send message';
      setError(errorMessage);

      // Update assistant message with error
      setMessages(prev =>
        prev.map(msg =>
          msg.id === assistantMessageId
            ? { ...msg, content: `Error: ${errorMessage}`, isThinking: false }
            : msg
        )
      );
    } finally {
      setIsLoading(false);
    }
  }, [isLoading]);

  const clearHistory = useCallback(() => {
    setMessages([]);
    setError(null);
    sessionIdRef.current = `session-${Date.now()}`;
  }, []);

  return {
    messages,
    isLoading,
    error,
    status,
    sendMessage,
    clearHistory,
    checkStatus,
  };
}
