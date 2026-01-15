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

import { User, Bot } from 'lucide-react';
import { clsx } from 'clsx';
import type { ChatMessage as ChatMessageType } from '../../types/api';

interface ChatMessageProps {
  message: ChatMessageType;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

  return (
    <div
      className={clsx(
        'flex gap-3 animate-fade-in',
        isUser && 'flex-row-reverse'
      )}
    >
      <div
        className={clsx(
          'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center',
          isUser ? 'bg-nvidia-gray-600' : 'bg-nvidia-green/20'
        )}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" />
        ) : (
          <Bot className="w-4 h-4 text-nvidia-green" />
        )}
      </div>

      <div
        className={clsx(
          'max-w-[80%] rounded-2xl px-4 py-3',
          isUser
            ? 'bg-nvidia-green text-black rounded-tr-sm'
            : 'bg-nvidia-gray-700 text-white rounded-tl-sm'
        )}
      >
        <p className="text-sm whitespace-pre-wrap">{message.content}</p>
        <span
          className={clsx(
            'text-xs mt-1 block',
            isUser ? 'text-black/60' : 'text-nvidia-gray-400'
          )}
        >
          {message.timestamp.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </span>
      </div>
    </div>
  );
}
