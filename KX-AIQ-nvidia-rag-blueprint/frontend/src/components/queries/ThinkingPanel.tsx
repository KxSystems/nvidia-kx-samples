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

import { Brain, ChevronDown, ChevronUp } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { clsx } from 'clsx';
import { Card } from '../common';

interface ThinkingPanelProps {
  content: string;
  isThinking: boolean;
  isStreaming?: boolean;
  modelName?: string;
}

// Inline spinner styles
const spinnerStyles = `
  @keyframes spinner-spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
  .thinking-spinner {
    width: 20px;
    height: 20px;
    border: 2px solid #76B900;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spinner-spin 1s linear infinite;
  }
`;

export function ThinkingPanel({ content, isThinking, isStreaming = false, modelName = 'LLAMA NEMOTRON SUPER' }: ThinkingPanelProps) {
  // Use isStreaming if provided, otherwise fall back to isThinking
  const showAsActive = isStreaming || isThinking;
  const [isExpanded, setIsExpanded] = useState(true);
  const contentRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom within container as content streams
  useEffect(() => {
    if (showAsActive && isExpanded && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [content, showAsActive, isExpanded]);

  // Clean the content - remove <think> tags, JSON, code blocks, and clean up formatting
  const cleanContent = content
    .replace(/<think>/g, '')
    .replace(/<\/think>/g, '')
    // Remove markdown code blocks (```json ... ```)
    .replace(/```json[\s\S]*?```/g, '')
    .replace(/```[\s\S]*?```/g, '')
    // Remove incomplete code blocks at the end
    .replace(/```json[\s\S]*$/g, '')
    .replace(/```[\s\S]*$/g, '')
    // Remove JSON arrays and objects
    .replace(/\[[\s\S]*?\{[\s\S]*?"query"[\s\S]*?\}[\s\S]*?\]/g, '')
    .replace(/\{[\s\S]*?"query"[\s\S]*?\}/g, '')
    // Remove lines containing JSON properties
    .replace(/^.*"query"\s*:.*$/gm, '')
    .replace(/^.*"report_section"\s*:.*$/gm, '')
    .replace(/^.*"rationale"\s*:.*$/gm, '')
    // Remove any remaining JSON-like content
    .replace(/\n\s*\[[\s\S]*$/g, '')
    .replace(/\n\s*\{[\s\S]*$/g, '')
    // Clean up extra whitespace
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  if (!content && !isThinking) return null;

  return (
    <div className="space-y-4">
      <style>{spinnerStyles}</style>
      {/* Header - matches QueryList header style */}
      <div
        className="flex items-center justify-between cursor-pointer"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className={clsx(
            'w-10 h-10 rounded-full flex items-center justify-center',
            showAsActive ? 'bg-nvidia-green/20' : 'bg-nvidia-green/10'
          )}>
            {showAsActive ? (
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <style>
                  {`.icon_spinner{transform-origin:center;animation:icon_spin .75s infinite linear}@keyframes icon_spin{100%{transform:rotate(360deg)}}`}
                </style>
                <path
                  d="M12,1A11,11,0,1,0,23,12,11,11,0,0,0,12,1Zm0,19a8,8,0,1,1,8-8A8,8,0,0,1,12,20Z"
                  opacity=".25"
                  fill="#76B900"
                />
                <path
                  d="M10.14,1.16a11,11,0,0,0-9,8.92A1.59,1.59,0,0,0,2.46,12,1.52,1.52,0,0,0,4.11,10.7a8,8,0,0,1,6.66-6.61A1.42,1.42,0,0,0,12,2.69h0A1.57,1.57,0,0,0,10.14,1.16Z"
                  className="icon_spinner"
                  fill="#76B900"
                />
              </svg>
            ) : (
              <Brain className="w-5 h-5 text-nvidia-green" />
            )}
          </div>
          <div>
            <h2 className="text-xl font-semibold text-white">
              {showAsActive ? 'AI-Q is thinking...' : 'Reasoning Complete'}
            </h2>
            <p className="text-sm text-nvidia-gray-400 mt-1">
              using {modelName}
            </p>
          </div>
        </div>
        <button className="p-2 text-nvidia-gray-400 hover:text-white transition-colors">
          {isExpanded ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
        </button>
      </div>

      {/* Content - same Card style as QueryCard */}
      {isExpanded && (
        <Card padding="sm">
          <div
            ref={contentRef}
            className="max-h-64 overflow-y-auto scrollbar-thin scroll-smooth"
          >
            {cleanContent ? (
              <pre className="text-sm text-nvidia-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
                {cleanContent}
              </pre>
            ) : showAsActive ? (
              <div className="space-y-3 animate-pulse">
                <div className="h-4 bg-nvidia-gray-700 rounded w-3/4"></div>
                <div className="h-4 bg-nvidia-gray-700 rounded w-full"></div>
                <div className="h-4 bg-nvidia-gray-700 rounded w-5/6"></div>
                <div className="h-4 bg-nvidia-gray-700 rounded w-2/3"></div>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>
        </Card>
      )}
    </div>
  );
}
