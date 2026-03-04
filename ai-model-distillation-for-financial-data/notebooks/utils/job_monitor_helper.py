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

import matplotlib.pyplot as plt
import pandas as pd
import time
import requests
from datetime import datetime
from IPython.display import clear_output
from pathlib import Path

def format_runtime(seconds):
    """Format runtime in seconds to a human-readable string."""
    if seconds is None:
        return "-"
    minutes, seconds = divmod(seconds, 60)
    if minutes > 0:
        return f"{int(minutes)}m {int(seconds)}s"
    return f"{int(seconds)}s"

def create_results_table(job_data):
    """Create a pandas DataFrame from job data."""
    rows = []
    for nim in job_data["nims"]:
        model_name = nim["model_name"]
        for eval in nim["evaluations"]:
            all_scores = eval["scores"]
            
            row = {
                "Model": model_name,
                "Eval Type": eval["eval_type"].upper(),
                "Percent Done": eval["progress"],
                "Runtime": format_runtime(eval["runtime_seconds"]),
                "Status": "Completed" if eval["finished_at"] else "Running",
                "Started": datetime.fromisoformat(eval["started_at"]).strftime("%H:%M:%S"),
                "Finished": datetime.fromisoformat(eval["finished_at"]).strftime("%H:%M:%S") if eval["finished_at"] else "-"
            }
            
            # Tool calling metrics
            if "function_name" in all_scores:
                row["Function name accuracy"] = all_scores["function_name"]
            
            if "function_name_and_args_accuracy" in all_scores:
                row["Function name + args accuracy (exact-match)"] = all_scores["function_name_and_args_accuracy"]
                
            if "tool_calling_correctness" in all_scores:
                row["Function name + args accuracy (LLM-judge)"] = all_scores["tool_calling_correctness"]
            
            # Generic classification metrics
            if "f1_score" in all_scores:
                row["F1 Score"] = all_scores["f1_score"]
            
            # Add any other scores with formatted names
            for score_name, score_value in all_scores.items():
                if score_name not in ["function_name", "tool_calling_correctness", "similarity", "function_name_and_args_accuracy", "f1_score"]:
                    formatted_name = score_name.replace("_", " ").title()
                    row[formatted_name] = score_value
            
            rows.append(row)
    
    if not rows:
        return pd.DataFrame(columns=["Model", "Eval Type", "Function Name Accuracy", "Tool Calling Correctness (LLM-Judge)", "Similarity (LLM-Judge)", "Percent Done", "Runtime", "Status", "Started", "Finished"])
    
    df = pd.DataFrame(rows)
    return df.sort_values(["Model", "Eval Type"])

def create_customization_table(job_data):
    """Create a pandas DataFrame from customization data."""
    customizations = []
    for nim in job_data["nims"]:
        model_name = nim["model_name"]
        for custom in nim["customizations"]:
            customizations.append({
                "Model": model_name,
                "Started": datetime.fromisoformat(custom["started_at"]).strftime("%H:%M:%S"),
                "Epochs Completed": custom["epochs_completed"],
                "Steps Completed": custom["steps_completed"],
                "Finished": datetime.fromisoformat(custom["finished_at"]).strftime("%H:%M:%S") if custom["finished_at"] else "-",
                "Status": "Completed" if custom["finished_at"] else "Running",
                "Runtime": format_runtime(custom["runtime_seconds"]),
                "Percent Done": custom["progress"],
            })
   
    if not customizations:
        customizations = pd.DataFrame(columns=["Model", "Started", "Epochs Completed", "Steps Completed", "Finished", "Runtime", "Percent Done"])
    customizations = pd.DataFrame(customizations)
    return customizations.sort_values(["Model"])

def get_job_status(api_base_url, job_id):
    """Get the current status of a job."""
    response = requests.get(f"{api_base_url}/api/jobs/{job_id}")
    response.raise_for_status()
    return response.json()

def monitor_job(api_base_url, job_id, poll_interval):
    """Monitor a job and display its progress in a table.
    
    Args:
        api_base_url: Base URL for the API
        job_id: Job ID to monitor
        poll_interval: Polling interval in seconds
    """
    print(f"Monitoring job {job_id}...")
    print("Press Ctrl+C to stop monitoring")
    
    # Track completed evaluations to avoid duplicate uploads
    completed_evaluations = set()
    
    while True:
        try:
            clear_output(wait=True)
            job_data = get_job_status(api_base_url, job_id)
            
            results_df = create_results_table(job_data)
            customizations_df = create_customization_table(job_data)
            clear_output(wait=True)
            print(f"Job Status: {job_data['status']}")
            print(f"Total Records: {job_data['num_records']}")
            print(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")
            print("\nResults:")
            display(results_df)
            print("\nCustomizations:")
            display(customizations_df)
            display(job_data)

            # Plot 1: Evaluation Scores
            if not results_df.empty:
                # Detect which metrics are available (tool calling vs generic)
                tool_calling_metrics = [
                    "Function name accuracy",
                    "Function name + args accuracy (exact-match)",
                    "Function name + args accuracy (LLM-judge)"
                ]
                generic_metrics = ["F1 Score"]
                
                # Determine which type of metrics to plot
                available_columns = results_df.columns.tolist()
                if any(metric in available_columns for metric in tool_calling_metrics):
                    metrics = [m for m in tool_calling_metrics if m in available_columns]
                elif "F1 Score" in available_columns:
                    metrics = generic_metrics
                else:
                    # Use any numeric columns that aren't metadata
                    metadata_cols = ["Model", "Eval Type", "Percent Done", "Runtime", "Status", "Started", "Finished"]
                    metrics = [col for col in available_columns if col not in metadata_cols]
                
                if metrics:
                    # Create single plot with all models
                    fig, ax = plt.subplots(figsize=(12, 6))
                    
                    # Pivot the data: Index = Model, Columns = Eval Type, Values = metric scores
                    # We need to handle multiple metrics, so we'll plot each metric
                    models = results_df['Model'].unique()
                    eval_types = results_df['Eval Type'].unique()
                    
                    # For grouped bar chart: x = models, grouped by eval_type
                    x = range(len(models))
                    width = 0.35
                    multiplier = 0
                    
                    for eval_type in eval_types:
                        offset = width * multiplier
                        eval_data = results_df[results_df['Eval Type'] == eval_type]
                        
                        # Get the metric values for this eval type, ordered by model
                        values = []
                        for model in models:
                            model_data = eval_data[eval_data['Model'] == model]
                            if not model_data.empty and metrics[0] in model_data.columns:
                                values.append(model_data[metrics[0]].values[0])
                            else:
                                values.append(0)
                        
                        ax.bar([xi + offset for xi in x], values, width, label=eval_type)
                        multiplier += 1
                    
                    ax.set_xlabel('Model', fontsize=11)
                    ax.set_ylabel('Score', fontsize=11)
                    ax.set_title('Evaluation Results', fontsize=14, fontweight='bold')
                    ax.set_xticks([xi + width/2 for xi in x])
                    ax.set_xticklabels(models, rotation=45, ha='right')
                    ax.legend(title='Eval Type')
                    ax.set_ylim(0, 1)
                    ax.grid(axis='y', linestyle='--', alpha=0.7)
                    plt.tight_layout()
                    plt.show()
                else:
                    fig, ax = plt.subplots(figsize=(6, 4))
                    ax.text(0.5, 0.5, "No Evaluation Data with Scores", ha='center', va='center')
                    ax.set_axis_off()
                    plt.tight_layout()
                    plt.show()
            else:
                fig, ax = plt.subplots(figsize=(6, 4))
                ax.text(0.5, 0.5, "No Evaluation Data", ha='center', va='center')
                ax.set_axis_off()
                plt.tight_layout()
                plt.show()

            plt.tight_layout()
            plt.show()                        
            time.sleep(poll_interval)

            # Check if job is completed or failed
            if job_data['status'] in ['completed', 'failed']:
                # print(f"\nJob monitoring complete! Final status: {job_data['status']}")
                if job_data['status'] == 'failed':
                    print("Job failed - check error details above")
                    if job_data.get('error'):
                        print(f"Error: {job_data['error']}")
                else:
                    print("Job completed successfully!")
                break

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
            break
        except Exception as e:
            print(f"\nError: {str(e)}")
            break
