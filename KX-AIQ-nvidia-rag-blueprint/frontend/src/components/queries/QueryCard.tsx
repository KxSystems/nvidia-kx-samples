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
import { ChevronDown, ChevronRight, Trash2, Check, RotateCcw } from 'lucide-react';
import { clsx } from 'clsx';
import { Button, Card, Textarea, Input } from '../common';
import type { GeneratedQuery } from '../../types/api';

interface QueryCardProps {
  query: GeneratedQuery;
  index: number;
  onUpdate: (index: number, query: GeneratedQuery) => void;
  onRemove: (index: number) => void;
  disabled?: boolean;
}

export function QueryCard({
  query,
  index,
  onUpdate,
  onRemove,
  disabled = false,
}: QueryCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [editedQuery, setEditedQuery] = useState(query.query);
  const [editedSection, setEditedSection] = useState(query.report_section);
  const [editedRationale, setEditedRationale] = useState(query.rationale);

  const hasChanges =
    editedQuery !== query.query ||
    editedSection !== query.report_section ||
    editedRationale !== query.rationale;

  const handleAccept = () => {
    if (hasChanges) {
      onUpdate(index, {
        query: editedQuery,
        report_section: editedSection,
        rationale: editedRationale,
      });
    }
    setIsExpanded(false);
  };

  const handleClear = () => {
    setEditedQuery(query.query);
    setEditedSection(query.report_section);
    setEditedRationale(query.rationale);
  };

  const handleToggle = () => {
    if (!disabled) {
      setIsExpanded(!isExpanded);
    }
  };

  return (
    <Card padding="sm" className="animate-fade-in">
      {/* Collapsed View - Query only */}
      <div
        className={clsx(
          'flex items-center gap-3 cursor-pointer',
          disabled && 'cursor-not-allowed opacity-60'
        )}
        onClick={handleToggle}
      >
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-nvidia-green/20 text-nvidia-green flex items-center justify-center text-sm font-semibold">
          {index + 1}
        </div>

        <div className="flex-1 min-w-0">
          <p className={clsx(
            'text-nvidia-gray-200 truncate',
            isExpanded && 'font-medium'
          )}>
            {query.query}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {!disabled && !isExpanded && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onRemove(index);
              }}
              className="p-1 text-nvidia-gray-400 hover:text-red-500 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
          <div className="text-nvidia-gray-400">
            {isExpanded ? (
              <ChevronDown className="w-5 h-5" />
            ) : (
              <ChevronRight className="w-5 h-5" />
            )}
          </div>
        </div>
      </div>

      {/* Expanded View - Editable fields */}
      {isExpanded && (
        <div className="mt-4 pt-4 border-t border-nvidia-gray-700 space-y-4">
          <div>
            <label className="block text-xs font-medium text-nvidia-gray-400 uppercase tracking-wide mb-2">
              Query
            </label>
            <Textarea
              value={editedQuery}
              onChange={(e) => setEditedQuery(e.target.value)}
              rows={2}
              disabled={disabled}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-nvidia-gray-400 uppercase tracking-wide mb-2">
              Report Section
            </label>
            <Input
              value={editedSection}
              onChange={(e) => setEditedSection(e.target.value)}
              disabled={disabled}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-nvidia-gray-400 uppercase tracking-wide mb-2">
              Rationale
            </label>
            <Textarea
              value={editedRationale}
              onChange={(e) => setEditedRationale(e.target.value)}
              rows={2}
              disabled={disabled}
            />
          </div>

          <div className="flex gap-2 pt-2">
            <Button
              size="sm"
              onClick={handleAccept}
              leftIcon={<Check className="w-3 h-3" />}
              disabled={disabled}
            >
              Accept
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleClear}
              leftIcon={<RotateCcw className="w-3 h-3" />}
              disabled={disabled || !hasChanges}
            >
              Clear
            </Button>
            <div className="flex-1" />
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onRemove(index)}
              leftIcon={<Trash2 className="w-3 h-3" />}
              className="text-red-400 hover:text-red-300 hover:bg-red-500/10"
              disabled={disabled}
            >
              Remove
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
