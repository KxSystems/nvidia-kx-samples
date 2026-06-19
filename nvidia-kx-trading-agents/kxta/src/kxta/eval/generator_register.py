# SPDX-FileCopyrightText: Copyright (c) 2025, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
"""
This file defines the workflow for evaluating the NVIDIA Trading Agents Blueprint.

Three types of generators are provided:
1. **gold**: Uses pre-defined expected outputs for comparison
2. **full**: Full NVIDIA Trading Agents Blueprint pipeline using the NVIDIA Trading Agents Blueprint workflow
3. **skeleton**: Template for custom evaluation implementations

### Implementation Guide:
The full generator integrates with the NVIDIA Trading Agents Blueprint pipeline to:
1. Generate research queries based on the topic and report organization
2. Execute the research pipeline including RAG search and web research
3. Generate a comprehensive report with citations
4. Compare against expected outputs for evaluation

### You can add more generators by following these steps:
1. Create a new generator class inheriting from KXTAGeneratorBase
2. Register the class with a unique name using the @register_generator decorator
3. Import the class in this file to populate the GeneratorRegistry
"""

import json
import logging

from nat.builder.builder import Builder
from nat.cli.register_workflow import register_function

from kxta.eval.config import KXTAEvaluatorWorkflowConfig
from kxta.eval.schema import AIResearcherEvalInput
from kxta.eval.schema import AIResearcherEvalOutput

logger = logging.getLogger(__name__)


class KXTAGeneratorBase:
    """
    Abstract base class for NVIDIA Trading Agents Blueprint generators.
    These generators create research outputs based on different strategies.
    """

    def __init__(self, config: KXTAEvaluatorWorkflowConfig, builder: Builder):
        self.config = config
        self.builder = builder

    def setup_generator(self):
        """Setup the generator with any necessary initialization."""
        pass

    async def generate_fn(self, kxta_input: AIResearcherEvalInput) -> AIResearcherEvalOutput:
        """
        Generate research output for a single research evaluation instance.
        This should be implemented by concrete generator classes.
        """
        raise NotImplementedError("Must be implemented by concrete generator classes")


class KXTAGeneratorRegistry:
    """
    Registry for NVIDIA Trading Agents Blueprint generators
    Manages different research generation strategies.
    """
    _generators = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a generator."""

        def decorator(generator_class):
            cls._generators[name] = generator_class
            return generator_class

        return decorator

    @classmethod
    def get(cls, name: str):
        """Get a generator by name."""
        if name not in cls._generators:
            raise ValueError(f"Generator '{name}' not found. Available: {list(cls._generators.keys())}")
        return cls._generators[name]

    @classmethod
    def list_generators(cls):
        """List all available generators."""
        return list(cls._generators.keys())


def register_generator(name: str):
    """Decorator to register a generator with the registry."""
    return KXTAGeneratorRegistry.register(name)


@register_function(config_type=KXTAEvaluatorWorkflowConfig)
async def kxta_evaluator_workflow(config: KXTAEvaluatorWorkflowConfig, builder: Builder):
    '''Workflow for evaluating NVIDIA Trading Agents Blueprint performance'''
    from nat.builder.function_info import FunctionInfo

    from kxta.eval.generators import register

    def _convert_input(input_str: str) -> AIResearcherEvalInput:
        '''Convert a JSON string into an KXTAResearchInput object.'''
        try:
            return AIResearcherEvalInput.model_validate(json.loads(input_str))
        except Exception as e:
            raise ValueError(f"Invalid input format: {e}") from e

    def _convert_output(kxta_input: AIResearcherEvalInput,
                        generated_queries: list[str],
                        final_report: str,
                        citations: str,
                        intermediate_steps: list[str] = None) -> AIResearcherEvalInput:
        '''Convert research results to KXTAResearchOutput object.'''
        return AIResearcherEvalOutput(id=kxta_input.id,
                                      generated_queries=generated_queries,
                                      final_report=final_report,
                                      citations=citations,
                                      intermediate_steps=intermediate_steps or [])

    def _get_generator() -> KXTAGeneratorBase:
        '''Fetch the generator based on the generation type such as gold, full etc.'''
        return KXTAGeneratorRegistry.get(config.generator.static_type())

    async def _response_fn(kxta_input_str: str) -> AIResearcherEvalOutput:
        '''Response function called for each KXTA evaluation instance'''
        kxta_input = _convert_input(kxta_input_str)
        # Call the generate function
        result = await _workflow.generate_fn(kxta_input)
        return result

    _generator_callable = _get_generator()
    _workflow = _generator_callable(config, builder)

    yield FunctionInfo.create(single_fn=_response_fn)
