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

import { Plus, Play } from 'lucide-react';
import { Button } from '../common';
import { QueryCard } from './QueryCard';
import { useWorkflowStore } from '../../store/workflowStore';
import type { GeneratedQuery } from '../../types/api';

interface QueryListProps {
  onExecutePlan: () => void;
}

export function QueryList({ onExecutePlan }: QueryListProps) {
  const { queries, isStreaming, planReady, updateQuery, removeQuery, addQuery } = useWorkflowStore();

  const handleAddQuery = () => {
    const newQuery: GeneratedQuery = {
      query: '',
      report_section: 'Custom Query',
      rationale: '',
    };
    addQuery(newQuery);
  };

  if (queries.length === 0) {
    return null;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">
            Research Plan
          </h2>
          <p className="text-sm text-nvidia-gray-400 mt-1">
            {queries.length} queries to execute
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleAddQuery}
            leftIcon={<Plus className="w-4 h-4" />}
            disabled={isStreaming}
          >
            Add Query
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        {queries.map((query, index) => (
          <QueryCard
            key={index}
            query={query}
            index={index}
            onUpdate={updateQuery}
            onRemove={removeQuery}
            disabled={isStreaming}
          />
        ))}
      </div>

      <div className="flex justify-end pt-4">
        <Button
          onClick={onExecutePlan}
          disabled={queries.length === 0 || isStreaming || !planReady}
          leftIcon={<Play className="w-4 h-4" />}
          size="lg"
        >
          Execute Plan
        </Button>
      </div>
    </div>
  );
}
