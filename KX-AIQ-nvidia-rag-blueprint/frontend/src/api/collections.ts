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

import type { Collection } from '../types/api';
import apiClient from './client';

// RAG collections response format
interface RAGCollectionsResponse {
  message: string;
  total_collections: number;
  collections: Array<{
    collection_name: string;
    num_entities: number;
    metadata_schema?: Array<{
      name: string;
      type: string;
    }>;
  }>;
}

// Default collections response format
interface DefaultCollectionsResponse {
  value: Array<{
    name: string;
    topic?: string;
    report_organization?: string;
  }>;
}


// Document list response
interface DocumentListResponse {
  message: string;
  total_documents: number;
  documents: Array<{
    document_name: string;
    metadata?: Record<string, string>;
  }>;
}

export async function getRAGCollections(): Promise<Collection[]> {
  const response = await apiClient.get<RAGCollectionsResponse>('/collections');
  const items = response.collections || [];
  return items.map(item => ({
    name: item.collection_name,
    description: `${item.num_entities} documents`,
    document_count: item.num_entities,
  }));
}

export async function getDefaultCollections(): Promise<Collection[]> {
  const response = await apiClient.get<DefaultCollectionsResponse>('/default_collections');
  const items = response.value || [];
  return items.map(item => ({
    name: item.name,
    description: item.topic || item.report_organization?.slice(0, 100),
  }));
}

export async function getAllCollections(): Promise<Collection[]> {
  try {
    // Get RAG collections first
    const ragCollections = await getRAGCollections();
    return ragCollections;
  } catch {
    // Fall back to default collections if RAG endpoint fails
    return getDefaultCollections();
  }
}

export async function createCollection(name: string, embeddingDimension: number = 1024): Promise<void> {
  const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

  const response = await fetch(`${API_BASE_URL}/collection`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      collection_name: name,
      embedding_dimension: embeddingDimension,
      vdb_endpoint: '', // Use default from backend
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || 'Failed to create collection');
  }
}

export async function deleteCollection(names: string[]): Promise<void> {
  const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

  const response = await fetch(`${API_BASE_URL}/collections`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(names),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || 'Failed to delete collection');
  }
}

export async function getDocuments(collectionName: string): Promise<DocumentListResponse> {
  const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

  const response = await fetch(`${API_BASE_URL}/documents?collection_name=${encodeURIComponent(collectionName)}`);

  if (!response.ok) {
    throw new Error('Failed to fetch documents');
  }

  return response.json();
}

export async function uploadDocuments(collectionName: string, files: File[]): Promise<void> {
  const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

  const formData = new FormData();

  // Add files
  files.forEach(file => {
    formData.append('documents', file);
  });

  // Add metadata as JSON string
  const metadata = {
    collection_name: collectionName,
  };
  formData.append('data', JSON.stringify(metadata));

  const response = await fetch(`${API_BASE_URL}/documents`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || 'Failed to upload documents');
  }
}

export async function deleteDocuments(collectionName: string, documentNames: string[]): Promise<void> {
  const API_BASE_URL = import.meta.env.VITE_API_URL || '/api';

  const response = await fetch(`${API_BASE_URL}/documents?collection_name=${encodeURIComponent(collectionName)}`, {
    method: 'DELETE',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(documentNames),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || 'Failed to delete documents');
  }
}
