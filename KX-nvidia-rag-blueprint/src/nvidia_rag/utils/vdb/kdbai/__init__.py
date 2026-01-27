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

"""KDB.AI Vector Database implementation for RAG applications."""

from nvidia_rag.utils.vdb.kdbai.kdbai_vdb import KdbaiVDB
from nvidia_rag.utils.vdb.kdbai.kdbai_filters import (
    milvus_to_kdbai_filter,
    build_source_filter,
    build_metadata_filter,
)

__all__ = [
    "KdbaiVDB",
    "milvus_to_kdbai_filter",
    "build_source_filter",
    "build_metadata_filter",
]
