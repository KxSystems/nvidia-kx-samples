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

import { apiClient } from './client';

export interface KdbDocsSettings {
  collection: string | null;
  available_collections: string[];
}

export async function getKdbDocsSettings(): Promise<KdbDocsSettings> {
  return apiClient.get<KdbDocsSettings>('/settings/kdb-docs');
}

export async function setKdbDocsSettings(collection: string | null): Promise<KdbDocsSettings> {
  return apiClient.put<KdbDocsSettings>('/settings/kdb-docs', { collection });
}
