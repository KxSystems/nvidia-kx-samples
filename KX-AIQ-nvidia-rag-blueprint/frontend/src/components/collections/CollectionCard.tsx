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

import { Database, FileText } from 'lucide-react';
import type { Collection } from '../../types/api';

interface CollectionCardProps {
  collection: Collection;
  isSelected: boolean;
  onSelect: (name: string) => void;
}

export function CollectionCard({ collection, isSelected, onSelect }: CollectionCardProps) {
  return (
    <div
      onClick={() => onSelect(collection.name)}
      className={`bg-nvidia-gray-800 border rounded-xl p-4 cursor-pointer transition-all duration-200 hover:border-nvidia-gray-600 ${
        isSelected ? 'border-nvidia-green ring-2 ring-nvidia-green/20' : 'border-nvidia-gray-700'
      }`}
    >
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-nvidia-green/20 text-nvidia-green flex items-center justify-center">
          <Database className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-white truncate">{collection.name}</h3>
          {collection.description && (
            <p className="text-sm text-nvidia-gray-400 mt-1 line-clamp-2">
              {collection.description}
            </p>
          )}
          {collection.document_count !== undefined && (
            <div className="flex items-center gap-1 mt-2 text-xs text-nvidia-gray-500">
              <FileText className="w-3 h-3" />
              <span>{collection.document_count} documents</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
