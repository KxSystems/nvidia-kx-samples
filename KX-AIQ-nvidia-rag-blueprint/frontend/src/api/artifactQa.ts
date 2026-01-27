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

import type { ArtifactQAInput, ArtifactQAOutput } from '../types/api';
import apiClient from './client';

export async function askArtifactQuestion(input: ArtifactQAInput): Promise<ArtifactQAOutput> {
  return apiClient.post<ArtifactQAOutput>('/artifact_qa', input);
}

export async function rewriteArtifact(
  artifact: string,
  instructions: string,
  ragCollection: string,
  useInternet: boolean = false
): Promise<ArtifactQAOutput> {
  const input: ArtifactQAInput = {
    artifact,
    question: instructions,
    rewrite_mode: 'entire',
    use_internet: useInternet,
    rag_collection: ragCollection,
  };
  return apiClient.post<ArtifactQAOutput>('/artifact_qa', input);
}
