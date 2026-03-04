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

import pytest

from src.config import (
    DataSplitConfig,
    LLMJudgeConfig,
    LoggingConfig,
    LoRAConfig,
    MLflowConfig,
    NIMConfig,
    NMPConfig,
    Settings,
    TrainingConfig,
)


@pytest.fixture
def base_configs():
    """Base configurations for Settings creation."""
    return {
        "nmp_config": NMPConfig(
            datastore_base_url="http://test-datastore",
            nemo_base_url="http://test-nemo",
            nim_base_url="http://test-nim",
        ),
        "nims": [
            NIMConfig(
                model_name="test/model",
                context_length=8192,
                model_type="llm",
            )
        ],
        "llm_judge_config": LLMJudgeConfig(
            model_name="test-judge",
            context_length=8192,
            deployment_type="local",
        ),
        "training_config": TrainingConfig(lora=LoRAConfig()),
        "logging_config": LoggingConfig(),
        "mlflow_config": MLflowConfig(),
    }


class TestSettings:
    """Test Settings validation."""

    def test_default_config_values_are_valid(self, base_configs):
        """Test that default configuration values pass validation."""
        settings = Settings(
            data_split_config=DataSplitConfig(),
            **base_configs,
        )

        assert settings.data_split_config.eval_size == 20

    def test_settings_initialization_all_params(self):
        """Test Settings initialization with all parameters."""
        settings = Settings(
            nmp_config=NMPConfig(
                datastore_base_url="http://test",
                nemo_base_url="http://test",
                nim_base_url="http://test",
            ),
            nims=[
                NIMConfig(
                    model_name="test/model",
                    context_length=1024,
                    model_type="llm",
                )
            ],
            llm_judge_config=LLMJudgeConfig(
                model_name="test", context_length=1024, deployment_type="local"
            ),
            training_config=TrainingConfig(lora=LoRAConfig()),
            data_split_config=DataSplitConfig(eval_size=50),
            logging_config=LoggingConfig(),
            mlflow_config=MLflowConfig(),
        )

        assert settings.data_split_config.eval_size == 50
