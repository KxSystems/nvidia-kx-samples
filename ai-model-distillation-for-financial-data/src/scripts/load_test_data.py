# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

import argparse
import json
from datetime import datetime, timezone
from typing import Any

import pykx as kx
from bson import ObjectId

from kdbx.connection import pykx_connection
from src.scripts.utils import validate_path


def create_openai_request_response(data: dict[str, Any]) -> dict[str, Any]:
    """Transform the data into an OpenAI-style request/response pair."""
    # Create a timestamp for the request
    timestamp = int(datetime.now(tz=timezone.utc).timestamp())

    # Create the request structure
    request = {
        "model": "not-a-model",
        "messages": data["messages"][:-1],
        "temperature": 0.7,
        "max_tokens": 1000,
    }

    if data.get("tools"):
        request["tools"] = data["tools"]

    # Create the response structure
    response = {
        "id": f"chatcmpl-{timestamp}",
        "object": "chat.completion",
        "created": timestamp,
        "model": "not-a-model",
        "choices": [
            {
                "index": 0,
                "message": data["messages"][-1],
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(data["messages"][0]["content"].split()),
            "completion_tokens": len(data["messages"][1]["content"].split()),
            "total_tokens": len(data["messages"][0]["content"].split())
            + len(data["messages"][1]["content"].split()),
        },
    }

    return {"timestamp": timestamp, "request": request, "response": response}


def _insert_doc(q: Any, doc: dict[str, Any]) -> None:
    """Insert a single document into the flywheel_logs table."""
    doc_id = str(ObjectId())
    request_json = json.dumps(doc.get("request", {}))
    response_json = json.dumps(doc.get("response", {}))

    # Convert timestamp: could be int (epoch) or string
    ts = doc.get("timestamp")
    if isinstance(ts, (int, float)):
        ts_val = kx.TimestampAtom(datetime.fromtimestamp(ts, tz=timezone.utc))
    elif isinstance(ts, str):
        ts_val = kx.TimestampAtom(datetime.fromisoformat(ts))
    else:
        ts_val = kx.TimestampAtom(datetime.now(tz=timezone.utc))

    q(
        "{[did;wid;cid;ts;req;resp] `flywheel_logs insert (did;wid;cid;ts;req;resp)}",
        kx.SymbolAtom(doc_id),
        kx.SymbolAtom(str(doc.get("workload_id", ""))),
        kx.SymbolAtom(str(doc.get("client_id", ""))),
        ts_val,
        request_json,
        response_json,
    )


def load_data_to_kdbx(
    workload_id: str = "",
    client_id: str = "",
    file_path: str = "aiva_primary_assistant_dataset.jsonl",
) -> None:
    """Load test data from JSONL file into KDB-X flywheel_logs table."""
    safe_path = validate_path(file_path, is_input=True, data_dir="data")

    with open(safe_path) as f:
        test_data = [json.loads(line) for line in f]

    with pykx_connection() as q:
        if test_data and test_data[0].get("workload_id"):
            # Document is already in the correct log format. However, for repeatable
            # integration tests we want the ability to override the `workload_id`
            # and `client_id` so that search queries scoped to those dynamic values
            # will find the freshly-loaded records. When callers provide non-empty
            # workload_id/client_id arguments we overwrite the existing values.

            print("Document is already in the log format. Loading with overrides.")

            for doc in test_data:
                # Ensure we do not mutate the original dict across iterations
                indexed_doc = dict(doc)

                # Override identifiers if provided by caller. This allows the
                # integration tests to generate unique IDs while reusing a static
                # JSONL fixture on disk.
                if workload_id:
                    indexed_doc["workload_id"] = workload_id
                if client_id:
                    indexed_doc["client_id"] = client_id

                _insert_doc(q, indexed_doc)
        else:
            # Document is not in the correct format, so we need to transform it
            for item in test_data:
                # Create OpenAI-style request/response pair
                doc = create_openai_request_response(item)

                doc["workload_id"] = workload_id

                if client_id:
                    doc["client_id"] = client_id

                _insert_doc(q, doc)

    print("Data loaded successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load test data into KDB-X flywheel_logs table."
    )
    parser.add_argument("--workload-id", help="Unique identifier for the workload")
    parser.add_argument("--file", help="Input JSONL file path")
    parser.add_argument("--client-id", help="Optional client identifier")

    args = parser.parse_args()

    load_data_to_kdbx(
        workload_id=args.workload_id,
        client_id=args.client_id,
        file_path=args.file,
    )
