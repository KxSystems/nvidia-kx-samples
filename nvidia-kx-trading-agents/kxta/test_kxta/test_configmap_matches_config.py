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
import yaml
from pathlib import Path
import subprocess
import tempfile
import re

def clean_helm_placeholders(yaml_content):
    """
    Removes Helm template placeholders ({{ ... }}) from YAML content and replaces them with 'from values.yaml'
    """
    # Pattern to match Helm template expressions
    pattern = r'\{\{.*?\}\}'
    
    # Replace all matches with 'from values.yaml'
    cleaned_content = re.sub(pattern, 'from values.yaml', yaml_content)
    return cleaned_content

def test_configmap_matches_config():
    """
    Tests that Helm configmap.yaml can be parsed and cleaned of Helm template placeholders.
    """
    current_dir = Path(__file__).parent
    # The Helm configmap embeds this file verbatim via {{ .Files.Get "files/app-config.yml" }},
    # so it is the actual config the chart ships. Compare the reference (local) config against it
    # directly — both are plain YAML; ${VAR:-default} entries parse as scalar strings.
    helm_app_config_path = current_dir / ".." / ".." / "deploy" / "helm" / "kxta" / "files" / "app-config.yml"
    reference_config_path = current_dir / ".." / ".." / "configs" / "config.yml"

    # Load the reference config file
    with open(reference_config_path, "r") as f:
        reference_config = yaml.safe_load(f)

    # Load the Helm chart's embedded app config
    with open(helm_app_config_path, "r") as f:
        configmap_data = yaml.safe_load(f)

    def check_keys(reference, generated, path="", differences=None):
        """
        Recursively checks if the generated dictionary has the same keys as the reference dictionary.
        Collects all differences and reports them at the end.
        Warns if 'eval' key is missing, errors for other missing keys.
        """
        if differences is None:
            differences = {
                'missing_keys': [],
                'extra_keys': [],
                'missing_eval': False
            }

        assert isinstance(reference, dict) == isinstance(generated, dict), "Types mismatch"

        if isinstance(reference, dict):
            ref_keys = set(reference.keys())
            gen_keys = set(generated.keys())
            
            # Pretty print the keys for debugging with path context
            if path:
                print(f"\nKeys at {path}:")
            else:
                print("\nTop level keys:")
            print(f"Reference keys: {sorted(ref_keys)}")
            print(f"Generated keys: {sorted(gen_keys)}")
            
            # Check for missing keys
            missing_keys = ref_keys - gen_keys
            if missing_keys:
                # If 'eval' is missing, just warn
                if 'eval' in missing_keys:
                    differences['missing_eval'] = True
                    missing_keys.remove('eval')
                
                # Collect other missing keys
                if missing_keys:
                    differences['missing_keys'].append((path, missing_keys))
            
            # Check for extra keys
            extra_keys = gen_keys - ref_keys
            if extra_keys:
                differences['extra_keys'].append((path, extra_keys))
            
            for key in reference:
                if key in generated:
                    new_path = f"{path}.{key}" if path else key
                    check_keys(reference[key], generated[key], new_path, differences)
        elif isinstance(reference, list):
            assert isinstance(generated, list), "Types mismatch: list vs not list"
            if reference and generated:
                if isinstance(reference[0], dict):
                  for i, (ref_item, gen_item) in enumerate(zip(reference, generated)):
                    new_path = f"{path}[{i}]" if path else f"[{i}]"
                    check_keys(ref_item, gen_item, new_path, differences)
                else:
                  assert len(reference) == len(generated)

        return differences

    # Compare the keys of the reference and generated dictionaries
    print("\nComparing config keys:")
    differences = check_keys(reference_config, configmap_data)
    
    # Report all differences at the end
    if differences['missing_eval']:
        print("\nWARNING: 'eval' key is missing in helm config")
        
    if differences['extra_keys']:
        print("\nWARNING: Extra keys in generated config at:")
        for path, keys in differences['extra_keys']:
            print(f"  - {path}: {sorted(keys)}")
    
    if differences['missing_keys']:
        error_msg = "\nERROR: Missing keys in helm config at:"
        for path, keys in differences['missing_keys']:
            error_msg += f"\n  - {path}: {sorted(keys)}"
        assert False, error_msg

