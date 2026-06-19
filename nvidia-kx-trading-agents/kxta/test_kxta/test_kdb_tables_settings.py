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
import pytest
import kxta.kdb_tables_settings as kts


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v):
        self.store[k] = v

    def delete(self, k):
        self.store.pop(k, None)

    def ping(self):
        return True


def test_env_fallback_when_no_redis(monkeypatch):
    monkeypatch.setattr(kts, "_client", lambda: None)
    monkeypatch.delenv("KDB_VISIBLE_TABLES", raising=False)
    assert kts.get_selected_tables() == []
    monkeypatch.setenv("KDB_VISIBLE_TABLES", "daily, trade ,quote")
    assert kts.get_selected_tables() == ["daily", "trade", "quote"]


def test_redis_roundtrip(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(kts, "_client", lambda: fake)
    monkeypatch.delenv("KDB_VISIBLE_TABLES", raising=False)
    assert kts.set_selected_tables(["daily", "quote"]) == ["daily", "quote"]
    assert kts.get_selected_tables() == ["daily", "quote"]
    # clearing -> empty (no env fallback)
    assert kts.set_selected_tables([]) == []
    assert kts.get_selected_tables() == []


def test_set_raises_without_redis(monkeypatch):
    monkeypatch.setattr(kts, "_client", lambda: None)
    with pytest.raises(RuntimeError):
        kts.set_selected_tables(["daily"])
