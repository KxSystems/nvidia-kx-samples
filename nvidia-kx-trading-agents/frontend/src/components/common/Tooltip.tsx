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

import { clsx } from 'clsx';
import type { ReactNode } from 'react';

/**
 * Instant styled hover tooltip (no native-title delay). Shows above the wrapped
 * element, centered; also appears on keyboard focus of the wrapped control.
 */
export function Tooltip({
  content,
  children,
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={clsx('relative inline-flex group/tip', className)}>
      {children}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover/tip:block group-focus-within/tip:block w-max max-w-[260px] rounded-lg bg-slate-900 text-white text-[11px] leading-snug px-2.5 py-1.5 shadow-xl z-40 text-center"
      >
        {content}
      </span>
    </span>
  );
}
