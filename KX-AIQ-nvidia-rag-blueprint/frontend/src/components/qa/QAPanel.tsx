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
import { Send, Edit3, ArrowLeft } from 'lucide-react';
import { Button, Card } from '../common';
import { ChatMessage } from './ChatMessage';
import { RewriteDialog } from './RewriteDialog';
import { useWorkflowStore } from '../../store/workflowStore';
import { useArtifactQA } from '../../hooks/useArtifactQA';
import { useUIStore } from '../../store/uiStore';

interface QAPanelProps {
  onBack: () => void;
}

export function QAPanel({ onBack }: QAPanelProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { chatHistory } = useWorkflowStore();
  const { ask, isLoading } = useArtifactQA();
  const { isRewriteDialogOpen, openRewriteDialog, closeRewriteDialog } = useUIStore();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const question = input;
    setInput('');
    await ask(question);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-white">
          Ask Questions
        </h2>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={onBack}
            leftIcon={<ArrowLeft className="w-4 h-4" />}
          >
            Back to Report
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={openRewriteDialog}
            leftIcon={<Edit3 className="w-4 h-4" />}
          >
            Rewrite Report
          </Button>
        </div>
      </div>

      <Card className="flex-1 flex flex-col min-h-0">
        <div className="flex-1 overflow-y-auto space-y-4 mb-4 scrollbar-thin">
          {chatHistory.length === 0 ? (
            <div className="text-center text-nvidia-gray-400 py-8">
              <p>Ask questions about the report or request changes.</p>
              <p className="text-sm mt-2">
                Try: "What are the key findings?" or "Add more details about..."
              </p>
            </div>
          ) : (
            chatHistory.map((message, index) => (
              <ChatMessage key={index} message={message} />
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question about the report..."
            className="input flex-1"
            disabled={isLoading}
          />
          <Button
            type="submit"
            disabled={!input.trim() || isLoading}
            isLoading={isLoading}
          >
            <Send className="w-4 h-4" />
          </Button>
        </form>
      </Card>

      <RewriteDialog
        isOpen={isRewriteDialogOpen}
        onClose={closeRewriteDialog}
      />
    </div>
  );
}
