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

import { create } from 'zustand';

interface UIState {
  // Modal states
  isRewriteDialogOpen: boolean;
  isSettingsOpen: boolean;

  // Sidebar state
  isSidebarOpen: boolean;

  // Theme
  theme: 'dark' | 'light';

  // Actions
  openRewriteDialog: () => void;
  closeRewriteDialog: () => void;
  openSettings: () => void;
  closeSettings: () => void;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
  setTheme: (theme: 'dark' | 'light') => void;
}

export const useUIStore = create<UIState>((set) => ({
  isRewriteDialogOpen: false,
  isSettingsOpen: false,
  isSidebarOpen: true,
  theme: 'dark',

  openRewriteDialog: () => set({ isRewriteDialogOpen: true }),
  closeRewriteDialog: () => set({ isRewriteDialogOpen: false }),
  openSettings: () => set({ isSettingsOpen: true }),
  closeSettings: () => set({ isSettingsOpen: false }),
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  setSidebarOpen: (open) => set({ isSidebarOpen: open }),
  setTheme: (theme) => set({ theme }),
}));
