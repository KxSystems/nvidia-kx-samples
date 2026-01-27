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

import { ExternalLink, FileText } from 'lucide-react';
import { Card } from '../common';

interface CitationListProps {
  citations: string;
}

export function CitationList({ citations }: CitationListProps) {
  if (!citations) {
    return null;
  }

  // Parse citations - they typically come as markdown or plain text
  const citationLines = citations
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => line.replace(/^\d+\.\s*/, '').trim());

  if (citationLines.length === 0) {
    return null;
  }

  return (
    <Card>
      <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <FileText className="w-5 h-5 text-nvidia-green" />
        Sources & Citations
      </h3>
      <ul className="space-y-2">
        {citationLines.map((citation, index) => {
          // Check if citation contains a URL
          const urlMatch = citation.match(/(https?:\/\/[^\s]+)/);
          const url = urlMatch ? urlMatch[1] : null;
          const text = url ? citation.replace(url, '').trim() : citation;

          return (
            <li
              key={index}
              className="flex items-start gap-2 text-sm text-nvidia-gray-300"
            >
              <span className="text-nvidia-green font-medium">{index + 1}.</span>
              <div className="flex-1">
                {text && <span>{text}</span>}
                {url && (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-nvidia-green hover:underline inline-flex items-center gap-1 ml-1"
                  >
                    {!text && url}
                    <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
