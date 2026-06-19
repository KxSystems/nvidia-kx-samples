# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import kxta.kdb_tables_settings as kts
import kxta.kdb_tools_nat as ktn


def test_empty_selection_passthrough(monkeypatch):
    monkeypatch.delenv("KDB_VISIBLE_TABLES", raising=False)
    monkeypatch.setattr(kts, "get_selected_tables", lambda: [])
    vis = ktn._visible_tables()
    # default base = KXTA_OWNED_TABLES
    assert vis is not None and "daily" in vis and "trade" in vis


def test_selection_narrows_within_allowlist(monkeypatch):
    monkeypatch.delenv("KDB_VISIBLE_TABLES", raising=False)
    monkeypatch.setattr(kts, "get_selected_tables", lambda: ["daily", "quote"])
    assert ktn._visible_tables() == {"daily", "quote"}


def test_selection_outside_allowlist_dropped(monkeypatch):
    monkeypatch.delenv("KDB_VISIBLE_TABLES", raising=False)
    # 'sec' is not in KXTA_OWNED_TABLES -> dropped by base intersection
    monkeypatch.setattr(kts, "get_selected_tables", lambda: ["daily", "sec"])
    assert ktn._visible_tables() == {"daily"}


def test_star_env_no_selection_means_all(monkeypatch):
    monkeypatch.setenv("KDB_VISIBLE_TABLES", "*")
    monkeypatch.setattr(kts, "get_selected_tables", lambda: [])
    assert ktn._visible_tables() is None


def test_star_env_with_selection_uses_selection(monkeypatch):
    monkeypatch.setenv("KDB_VISIBLE_TABLES", "*")
    monkeypatch.setattr(kts, "get_selected_tables", lambda: ["daily"])
    assert ktn._visible_tables() == {"daily"}
