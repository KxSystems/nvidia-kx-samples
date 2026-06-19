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

from kxta.schema import GenerateSummaryStateInput, GeneratedQuery


def _q():
    return [GeneratedQuery(query="q", report_section="All", rationale="r")]


def test_input_accepts_per_source_flags_with_defaults():
    inp = GenerateSummaryStateInput(
        topic="t", report_organization="o", queries=_q(), search_web=False,
        rag_collection="demo", llm_name="instruct_llm",
    )
    assert inp.use_web_search is False
    assert inp.use_market_data is False
    assert inp.use_news_headlines is False
    assert inp.use_fundamentals is False
    assert inp.use_sec_filings is False
    assert inp.use_macro_economic is False


def test_input_accepts_enabling_sources():
    inp = GenerateSummaryStateInput(
        topic="t", report_organization="o", queries=_q(), search_web=False,
        rag_collection="demo", llm_name="instruct_llm",
        use_market_data=True, use_macro_economic=True,
    )
    assert inp.use_market_data is True and inp.use_macro_economic is True
