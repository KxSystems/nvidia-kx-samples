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

export interface KdbTablesSettings {
  selected_tables: string[];
  available_tables: string[];
  table_rows: Record<string, number | null>;
}

export async function getKdbTablesSettings(): Promise<KdbTablesSettings> {
  return apiClient.get<KdbTablesSettings>('/settings/kdb-tables');
}

export async function setKdbTablesSettings(tables: string[]): Promise<KdbTablesSettings> {
  return apiClient.put<KdbTablesSettings>('/settings/kdb-tables', { tables });
}
