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

import { useState, useRef, useEffect } from 'react';
import {
  Send,
  Trash2,
  Database,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  HelpCircle,
  Loader2,
} from 'lucide-react';
import { Card, Button } from '../common';
import { KDBChatMessage } from './KDBChatMessage';
import { useKDBChat } from '../../hooks/useKDBChat';

const EXAMPLE_QUERIES = [
  "What tables are available?",
  "Show me the schema for the daily table",
  "What are the latest AAPL prices?",
  "What's the average trading volume for NVDA?",
  "Compare closing prices for TSLA and GOOG",
  "Which stock had the highest volume today?",
];

export function KDBChatPanel() {
  const [input, setInput] = useState('');
  const [showExamples, setShowExamples] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const {
    messages,
    isLoading,
    error,
    status,
    sendMessage,
    clearHistory,
    checkStatus,
  } = useKDBChat();

  // Check status on mount
  useEffect(() => {
    checkStatus();
  }, [checkStatus]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const message = input.trim();
    setInput('');
    await sendMessage(message);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleExampleClick = (query: string) => {
    setInput(query);
    setShowExamples(false);
    inputRef.current?.focus();
  };

  return (
    <Card className="flex flex-col h-[600px]">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-nvidia-gray-700">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-nvidia-gray-800 rounded-lg flex items-center justify-center">
            <Database className="w-5 h-5 text-nvidia-green" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">KDB-X Data Chat</h2>
            <p className="text-xs text-nvidia-gray-400">
              Ask questions about your financial data in natural language
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Connection status */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-nvidia-gray-800">
            {status === null ? (
              <Loader2 className="w-4 h-4 text-nvidia-gray-400 animate-spin" />
            ) : status.connected ? (
              <CheckCircle className="w-4 h-4 text-nvidia-green" />
            ) : (
              <AlertCircle className="w-4 h-4 text-red-400" />
            )}
            <span className="text-xs text-nvidia-gray-400">
              {status === null ? 'Checking...' : status.connected ? 'Connected' : 'Disconnected'}
            </span>
          </div>

          {/* Refresh status */}
          <button
            onClick={checkStatus}
            className="p-2 rounded-lg hover:bg-nvidia-gray-800 text-nvidia-gray-400 hover:text-white transition-colors"
            title="Refresh connection status"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          {/* Clear history */}
          {messages.length > 0 && (
            <button
              onClick={clearHistory}
              className="p-2 rounded-lg hover:bg-nvidia-gray-800 text-nvidia-gray-400 hover:text-white transition-colors"
              title="Clear chat history"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 p-3 mt-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* Connection warning */}
      {status && !status.connected && (
        <div className="flex items-center gap-2 p-3 mt-4 rounded-lg bg-yellow-500/10 border border-yellow-500/30 text-yellow-400">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <div className="text-sm">
            <p className="font-medium">KDB+ is not connected</p>
            <p className="text-xs mt-1 text-yellow-400/80">{status.message}</p>
          </div>
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4 min-h-0">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <Database className="w-12 h-12 text-nvidia-gray-600 mb-4" />
            <h3 className="text-lg font-medium text-nvidia-gray-400 mb-2">
              Ask about your data
            </h3>
            <p className="text-sm text-nvidia-gray-500 max-w-md mb-4">
              Query your KDB+ financial database using natural language. I'll generate
              the SQL and show you the results.
            </p>
            <button
              onClick={() => setShowExamples(!showExamples)}
              className="flex items-center gap-2 text-sm text-nvidia-green hover:text-nvidia-green/80 transition-colors"
            >
              <HelpCircle className="w-4 h-4" />
              {showExamples ? 'Hide examples' : 'Show example queries'}
            </button>

            {showExamples && (
              <div className="mt-4 grid gap-2 w-full max-w-md">
                {EXAMPLE_QUERIES.map((query, i) => (
                  <button
                    key={i}
                    onClick={() => handleExampleClick(query)}
                    className="text-left px-3 py-2 rounded-lg bg-nvidia-gray-800 hover:bg-nvidia-gray-700 text-sm text-nvidia-gray-300 hover:text-white transition-colors"
                  >
                    {query}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <>
            {messages.map((message) => (
              <KDBChatMessage key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input area */}
      <form onSubmit={handleSubmit} className="pt-4 border-t border-nvidia-gray-700">
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your financial data..."
              disabled={isLoading || !status?.connected}
              className="w-full px-4 py-3 bg-nvidia-gray-800 border border-nvidia-gray-600 rounded-xl text-white placeholder-nvidia-gray-500 focus:outline-none focus:border-nvidia-green focus:ring-1 focus:ring-nvidia-green disabled:opacity-50 disabled:cursor-not-allowed resize-none"
              rows={1}
              style={{ minHeight: '48px', maxHeight: '120px' }}
            />
          </div>
          <Button
            type="submit"
            disabled={!input.trim() || isLoading || !status?.connected}
            className="px-4"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </Button>
        </div>
        <p className="text-xs text-nvidia-gray-500 mt-2">
          Press Enter to send, Shift+Enter for new line
        </p>
      </form>
    </Card>
  );
}
