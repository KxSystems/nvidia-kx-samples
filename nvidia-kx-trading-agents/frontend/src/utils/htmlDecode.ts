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

/**
 * Decode HTML entities in a string.
 * Handles common entities like &amp;, &lt;, &gt;, &#x27;, &quot;, etc.
 */
export function decodeHtmlEntities(text: string): string {
  if (!text) return text;

  // Use a textarea to decode HTML entities (browser-native decoding)
  const textarea = document.createElement('textarea');
  textarea.innerHTML = text;
  return textarea.value;
}

/**
 * Recursively decode HTML entities in an object's string values.
 */
export function decodeHtmlEntitiesInObject<T>(obj: T): T {
  if (typeof obj === 'string') {
    return decodeHtmlEntities(obj) as T;
  }
  if (Array.isArray(obj)) {
    return obj.map(item => decodeHtmlEntitiesInObject(item)) as T;
  }
  if (obj && typeof obj === 'object') {
    const decoded: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      decoded[key] = decodeHtmlEntitiesInObject(value);
    }
    return decoded as T;
  }
  return obj;
}
