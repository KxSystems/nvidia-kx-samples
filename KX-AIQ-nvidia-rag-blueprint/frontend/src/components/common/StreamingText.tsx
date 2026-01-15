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

import { clsx } from 'clsx';

interface StreamingTextProps {
  content: string;
  className?: string;
  showCursor?: boolean;
}

export function StreamingText({
  content,
  className,
  showCursor = true,
}: StreamingTextProps) {
  return (
    <div className={clsx('relative', className)}>
      <span className="whitespace-pre-wrap">{content}</span>
      {showCursor && (
        <span className="inline-block w-2 h-5 ml-0.5 bg-nvidia-green animate-pulse" />
      )}
    </div>
  );
}

interface StreamingProgressProps {
  step: string;
  content?: string;
}

export function StreamingProgress({ step, content }: StreamingProgressProps) {
  const stepLabels: Record<string, string> = {
    generating_questions: 'Generating research queries',
    web_research: 'Searching the web',
    rag_search: 'Searching documents',
    running_summary: 'Writing report',
    reflect_on_summary: 'Improving report',
    final_report: 'Finalizing report',
  };

  const label = stepLabels[step] || step;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-nvidia-green animate-pulse" />
        <span className="text-sm font-medium text-nvidia-gray-200">{label}</span>
      </div>
      {content && (
        <p className="text-sm text-nvidia-gray-400 ml-5 line-clamp-2">{content}</p>
      )}
    </div>
  );
}
