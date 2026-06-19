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

import { CollectionCard } from './CollectionCard';
import type { Collection } from '../../types/api';

interface CollectionSelectorProps {
  collections: Collection[];
  selectedCollection: string;
  onSelect: (name: string) => void;
}

export function CollectionSelector({
  collections,
  selectedCollection,
  onSelect,
}: CollectionSelectorProps) {
  if (collections.length === 0) {
    return (
      <div className="text-center py-8 text-nvidia-gray-400">
        <p>No collections available.</p>
        <p className="text-sm mt-1">Please configure your RAG server.</p>
      </div>
    );
  }

  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {collections.map((collection) => (
        <CollectionCard
          key={collection.name}
          collection={collection}
          isSelected={selectedCollection === collection.name}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
