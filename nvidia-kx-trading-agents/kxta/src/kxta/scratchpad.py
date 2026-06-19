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

"""Persistent JSONL audit log per research session for debugging, compliance, and eval data."""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCRATCHPAD_DIR = os.getenv("SCRATCHPAD_DIR", "./scratchpad")


class Scratchpad:
    """
    Persistent JSONL audit log for a research session.

    Entry types: init, query_generated, search_result, relevancy_check,
                 reflection, report_update, error, finalize
    """

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())

    def log(self, entry_type: str, data: dict) -> None:
        """Append one JSON line to {SCRATCHPAD_DIR}/{session_id}.jsonl. Fire-and-forget."""
        try:
            dirpath = Path(SCRATCHPAD_DIR)
            dirpath.mkdir(parents=True, exist_ok=True)
            filepath = dirpath / f"{self.session_id}.jsonl"
            entry = {
                "session_id": self.session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": entry_type,
                "data": data,
            }
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Scratchpad log error (non-fatal): {e}")

    @classmethod
    def read(cls, session_id: str) -> list[dict]:
        """Read JSONL back, skipping malformed lines."""
        filepath = Path(SCRATCHPAD_DIR) / f"{session_id}.jsonl"
        if not filepath.exists():
            return []
        entries = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug(f"Skipping malformed JSONL line in {session_id}")
                    continue
        return entries
