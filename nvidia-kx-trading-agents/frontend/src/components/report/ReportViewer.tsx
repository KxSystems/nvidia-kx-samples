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

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { clsx } from 'clsx';
import { DecisionHeader, parseDecisionHeader } from './DecisionHeader';
import { SourcesTable } from './CitationList';

interface ReportViewerProps {
  content: string;
  className?: string;
}

/**
 * Split the report into the prose body and the verbose sources tail the backend
 * appends ("\n\n ## Sources \n\n" — note the leading space — or, on the LLM-timeout
 * path, the same blob after '----' with no heading). The tail is re-rendered as a
 * structured, deduplicated table instead of raw Query/Answer dumps.
 */
function splitSourcesTail(content: string): { body: string; tail: string } {
  const headingMatch = content.match(/\n\s*#{1,3}\s+Sources\s*\n/);
  if (headingMatch && headingMatch.index !== undefined) {
    return {
      body: content.slice(0, headingMatch.index),
      tail: content.slice(headingMatch.index + headingMatch[0].length),
    };
  }
  const entryMatch = content.match(/\n\s*-{3,}\s*\n\s*\*\*Source\*\*\s*\d+/);
  if (entryMatch && entryMatch.index !== undefined) {
    return { body: content.slice(0, entryMatch.index), tail: content.slice(entryMatch.index) };
  }
  return { body: content, tail: '' };
}

export function ReportViewer({ content, className }: ReportViewerProps) {
  if (!content) {
    return null;
  }

  const { body, tail } = splitSourcesTail(content);

  // Render the report's Decision Header (Signal / Conviction / levels / catalysts)
  // as a styled block; fall back to plain markdown when it isn't present.
  const parsed = parseDecisionHeader(body);

  return (
    <div className={clsx('markdown-content', className)}>
      {parsed && <DecisionHeader fields={parsed.fields} />}
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {parsed ? parsed.body : body}
      </ReactMarkdown>
      {/* Sources, formatted: rendered from the report's own tail so it always
          appears exactly where the section used to be. */}
      {tail && <SourcesTable citations={tail} className="mt-8" />}
    </div>
  );
}
