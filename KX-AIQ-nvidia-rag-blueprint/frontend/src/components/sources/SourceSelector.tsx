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

import { Globe, Database, Server, Check, ChevronDown, ChevronUp, Plus, Upload } from 'lucide-react';
import { useState } from 'react';
import { clsx } from 'clsx';
import { useWorkflowStore } from '../../store/workflowStore';
import { NewCollectionDialog, FileUploadDialog } from '../collections';
import type { Collection } from '../../types/api';

interface SourceSelectorProps {
  collections: Collection[];
  onCollectionsChange?: () => void;
}

interface SourceCardProps {
  id: 'webSearch' | 'kdbx' | 'rag';
  title: string;
  description: string;
  icon: React.ReactNode;
  isSelected: boolean;
  onToggle: () => void;
  children?: React.ReactNode;
  expandable?: boolean;
}

function SourceCard({
  title,
  description,
  icon,
  isSelected,
  onToggle,
  children,
  expandable = false,
}: SourceCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleClick = () => {
    onToggle();
    if (expandable && !isSelected) {
      setIsExpanded(true);
    }
  };

  const handleExpandToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsExpanded(!isExpanded);
  };

  return (
    <div
      className={clsx(
        'rounded-xl border-2 transition-all duration-200 overflow-hidden',
        isSelected
          ? 'border-nvidia-green bg-nvidia-green/10'
          : 'border-nvidia-gray-700 bg-nvidia-gray-800 hover:border-nvidia-gray-600'
      )}
    >
      <div
        className="p-6 cursor-pointer"
        onClick={handleClick}
      >
        <div className="flex items-start gap-4">
          <div
            className={clsx(
              'flex-shrink-0 w-12 h-12 rounded-xl flex items-center justify-center transition-colors',
              isSelected
                ? 'bg-nvidia-green text-black'
                : 'bg-nvidia-gray-700 text-nvidia-gray-400'
            )}
          >
            {icon}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">{title}</h3>
              <div className="flex items-center gap-2">
                {expandable && isSelected && (
                  <button
                    onClick={handleExpandToggle}
                    className="p-1 text-nvidia-gray-400 hover:text-white transition-colors"
                  >
                    {isExpanded ? (
                      <ChevronUp className="w-5 h-5" />
                    ) : (
                      <ChevronDown className="w-5 h-5" />
                    )}
                  </button>
                )}
                <div
                  className={clsx(
                    'w-6 h-6 rounded-full border-2 flex items-center justify-center transition-all',
                    isSelected
                      ? 'border-nvidia-green bg-nvidia-green'
                      : 'border-nvidia-gray-600'
                  )}
                >
                  {isSelected && <Check className="w-4 h-4 text-black" />}
                </div>
              </div>
            </div>
            <p className="text-sm text-nvidia-gray-400 mt-1">{description}</p>
          </div>
        </div>
      </div>

      {expandable && isSelected && isExpanded && children && (
        <div className="px-6 pb-6 pt-2 border-t border-nvidia-gray-700">
          {children}
        </div>
      )}
    </div>
  );
}

export function SourceSelector({ collections, onCollectionsChange }: SourceSelectorProps) {
  const {
    sources,
    selectedCollections,
    toggleSource,
    toggleCollection,
  } = useWorkflowStore();

  const [isNewCollectionOpen, setIsNewCollectionOpen] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [uploadCollectionName, setUploadCollectionName] = useState('');

  const handleOpenUpload = (collectionName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setUploadCollectionName(collectionName);
    setIsUploadOpen(true);
  };

  const handleCollectionCreated = () => {
    onCollectionsChange?.();
  };

  const handleFilesUploaded = () => {
    onCollectionsChange?.();
  };

  return (
    <>
      <div className="space-y-4">
        <SourceCard
          id="kdbx"
          title="KDB-X Database"
          description="Query financial time-series data from KDB-X via MCP"
          icon={<Server className="w-6 h-6" />}
          isSelected={sources.kdbx}
          onToggle={() => toggleSource('kdbx')}
        />

        <SourceCard
          id="rag"
          title="RAG Collections"
          description="Search through your uploaded document collections"
          icon={<Database className="w-6 h-6" />}
          isSelected={sources.rag}
          onToggle={() => toggleSource('rag')}
          expandable
        >
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm text-nvidia-gray-300 font-medium">
                Select collections to search:
              </p>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setIsNewCollectionOpen(true);
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-nvidia-green bg-nvidia-green/10 border border-nvidia-green/30 rounded-lg hover:bg-nvidia-green/20 transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                New Collection
              </button>
            </div>
            {collections.length === 0 ? (
              <p className="text-sm text-nvidia-gray-500">No collections available</p>
            ) : (
              <div className="grid gap-2">
                {collections.map((collection) => (
                  <div
                    key={collection.name}
                    className={clsx(
                      'flex items-center justify-between p-3 rounded-lg border transition-all',
                      selectedCollections.includes(collection.name)
                        ? 'border-nvidia-green bg-nvidia-green/10'
                        : 'border-nvidia-gray-600 bg-nvidia-gray-700/50'
                    )}
                  >
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleCollection(collection.name);
                      }}
                      className="flex items-center gap-3 flex-1 text-left"
                    >
                      <div
                        className={clsx(
                          'w-5 h-5 rounded border-2 flex items-center justify-center transition-all flex-shrink-0',
                          selectedCollections.includes(collection.name)
                            ? 'border-nvidia-green bg-nvidia-green'
                            : 'border-nvidia-gray-500'
                        )}
                      >
                        {selectedCollections.includes(collection.name) && (
                          <Check className="w-3 h-3 text-black" />
                        )}
                      </div>
                      <div>
                        <span className={clsx(
                          'font-medium',
                          selectedCollections.includes(collection.name) ? 'text-white' : 'text-nvidia-gray-300'
                        )}>
                          {collection.name}
                        </span>
                        {collection.document_count !== undefined && (
                          <span className="text-xs text-nvidia-gray-500 ml-2">
                            ({collection.document_count} docs)
                          </span>
                        )}
                      </div>
                    </button>
                    <button
                      onClick={(e) => handleOpenUpload(collection.name, e)}
                      className="p-2 text-nvidia-gray-400 hover:text-nvidia-green hover:bg-nvidia-gray-700 rounded-lg transition-colors"
                      title="Upload files to this collection"
                    >
                      <Upload className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </SourceCard>

        <SourceCard
          id="webSearch"
          title="Web Search"
          description="Search the internet for up-to-date information using Tavily"
          icon={<Globe className="w-6 h-6" />}
          isSelected={sources.webSearch}
          onToggle={() => toggleSource('webSearch')}
        />
      </div>

      <NewCollectionDialog
        isOpen={isNewCollectionOpen}
        onClose={() => setIsNewCollectionOpen(false)}
        onCreated={handleCollectionCreated}
      />

      <FileUploadDialog
        isOpen={isUploadOpen}
        collectionName={uploadCollectionName}
        onClose={() => setIsUploadOpen(false)}
        onUploaded={handleFilesUploaded}
      />
    </>
  );
}
