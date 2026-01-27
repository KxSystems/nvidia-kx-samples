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

import { useState } from 'react';
import { User, Bot, ChevronDown, ChevronRight, Database, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';
import type { KDBChatMessage as KDBChatMessageType } from '../../api/kdbChat';

interface KDBChatMessageProps {
  message: KDBChatMessageType;
}

// Strip <think>...</think> tags from LLM responses (Nemotron model adds these)
function stripThinkingTags(content: string): string {
  if (!content) return content;
  return content.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
}

export function KDBChatMessage({ message }: KDBChatMessageProps) {
  const [showQuery, setShowQuery] = useState(false);
  const [showData, setShowData] = useState(true);
  const isUser = message.role === 'user';

  // Strip thinking tags from content
  const displayContent = isUser ? message.content : stripThinkingTags(message.content);

  // Parse data if it's a JSON string
  const parsedData = (() => {
    if (!message.data) return null;
    if (Array.isArray(message.data)) return message.data;
    if (typeof message.data === 'string') {
      try {
        return JSON.parse(message.data);
      } catch {
        return null;
      }
    }
    return null;
  })();

  return (
    <div
      className={clsx(
        'flex gap-3 animate-fade-in',
        isUser && 'flex-row-reverse'
      )}
    >
      <div
        className={clsx(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser ? 'bg-nvidia-gray-600' : 'bg-nvidia-green/20'
        )}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" />
        ) : message.isThinking ? (
          <Loader2 className="w-4 h-4 text-nvidia-green animate-spin" />
        ) : (
          <Bot className="w-4 h-4 text-nvidia-green" />
        )}
      </div>

      <div
        className={clsx(
          'max-w-[85%] rounded-2xl px-4 py-3',
          isUser
            ? 'bg-nvidia-green text-black rounded-tr-sm'
            : 'bg-nvidia-gray-700 text-white rounded-tl-sm'
        )}
      >
        {/* Main content */}
        <p className={clsx(
          'text-sm whitespace-pre-wrap',
          message.isThinking && 'text-nvidia-gray-300 italic'
        )}>
          {displayContent || (message.isThinking ? 'Thinking...' : '')}
        </p>

        {/* SQL Query section (collapsible) */}
        {message.sqlQuery && !isUser && (
          <div className="mt-3 border-t border-nvidia-gray-600 pt-3">
            <button
              onClick={() => setShowQuery(!showQuery)}
              className="flex items-center gap-2 text-xs text-nvidia-gray-400 hover:text-nvidia-green transition-colors"
            >
              {showQuery ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
              <Database className="w-3 h-3" />
              SQL Query
            </button>
            {showQuery && (
              <pre className="mt-2 p-2 bg-nvidia-gray-800 rounded text-xs text-nvidia-gray-300 overflow-x-auto font-mono">
                {message.sqlQuery}
              </pre>
            )}
          </div>
        )}

        {/* Data table section */}
        {parsedData && Array.isArray(parsedData) && parsedData.length > 0 && !isUser && (
          <div className="mt-3 border-t border-nvidia-gray-600 pt-3">
            <button
              onClick={() => setShowData(!showData)}
              className="flex items-center gap-2 text-xs text-nvidia-gray-400 hover:text-nvidia-green transition-colors mb-2"
            >
              {showData ? (
                <ChevronDown className="w-3 h-3" />
              ) : (
                <ChevronRight className="w-3 h-3" />
              )}
              Results ({parsedData.length} rows)
            </button>
            {showData && (
              <div className="overflow-x-auto max-h-64 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="bg-nvidia-gray-800 sticky top-0">
                    <tr>
                      {Object.keys(parsedData[0] || {}).map((key) => (
                        <th
                          key={key}
                          className="px-2 py-1 text-left text-nvidia-gray-400 font-medium border-b border-nvidia-gray-600"
                        >
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {parsedData.slice(0, 50).map((row, i) => (
                      <tr
                        key={i}
                        className="hover:bg-nvidia-gray-600/50 transition-colors"
                      >
                        {Object.values(row as Record<string, unknown>).map((value, j) => (
                          <td
                            key={j}
                            className="px-2 py-1 text-nvidia-gray-300 border-b border-nvidia-gray-700"
                          >
                            {formatCellValue(value)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {parsedData.length > 50 && (
                  <p className="text-xs text-nvidia-gray-500 mt-2 text-center">
                    Showing first 50 of {parsedData.length} rows
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {/* Timestamp */}
        <span
          className={clsx(
            'text-xs mt-2 block',
            isUser ? 'text-black/60' : 'text-nvidia-gray-400'
          )}
        >
          {message.timestamp.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </span>
      </div>
    </div>
  );
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return '-';
  if (typeof value === 'number') {
    // Format numbers nicely
    if (Number.isInteger(value)) {
      return value.toLocaleString();
    }
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
