# SPDX-FileCopyrightText: Copyright (c) 2026 KX Systems, Inc. All rights reserved.
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

# eksctl cluster configuration for Data Flywheel Blueprint
# Generated from eksctl-cluster.yaml.tpl — do not edit the .yaml directly.
# Usage: envsubst < deploy/eksctl-cluster.yaml.tpl > deploy/eksctl-cluster.yaml
#        AWS_PROFILE=${AWS_PROFILE} eksctl create cluster -f deploy/eksctl-cluster.yaml
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: ${EKS_CLUSTER_NAME}
  region: ${AWS_REGION}
  version: "1.31"
  tags:
    project: data-flywheel
    environment: dev

iam:
  withOIDC: true

vpc:
  id: ${VPC_ID}
  subnets:
    public:
      ${AWS_REGION}a:
        id: ${SUBNET_PUBLIC_2A}
      ${AWS_REGION}b:
        id: ${SUBNET_PUBLIC_2B}
    private:
      ${AWS_REGION}a:
        id: ${SUBNET_PRIVATE_2A}
      ${AWS_REGION}b:
        id: ${SUBNET_PRIVATE_2B}

addons:
  - name: vpc-cni
    version: latest
  - name: coredns
    version: latest
  - name: kube-proxy
    version: latest
  - name: aws-ebs-csi-driver
    version: latest
    wellKnownPolicies:
      ebsCSIController: true

managedNodeGroups:
  # System node group — NeMo services, Redis, KDB-X, API, MLflow
  - name: system
    instanceType: m5.2xlarge
    desiredCapacity: 2
    minSize: 1
    maxSize: 4
    volumeSize: 100
    volumeType: gp3
    privateNetworking: true
    subnets:
      - ${SUBNET_PRIVATE_2A}
      - ${SUBNET_PRIVATE_2B}
    labels:
      role: system
    tags:
      project: data-flywheel
      nodegroup: system
    iam:
      withAddonPolicies:
        ebs: true

  # GPU node group — NIM inference, fine-tuning, LLM judge
  - name: gpu
    instanceType: p4d.24xlarge
    desiredCapacity: 2
    minSize: 0
    maxSize: 4
    volumeSize: 500
    volumeType: gp3
    privateNetworking: true
    subnets:
      - ${SUBNET_PRIVATE_2A}
      - ${SUBNET_PRIVATE_2B}
    labels:
      role: gpu
      nvidia.com/gpu.present: "true"
    taints:
      - key: nvidia.com/gpu
        value: "true"
        effect: NoSchedule
    tags:
      project: data-flywheel
      nodegroup: gpu
    iam:
      withAddonPolicies:
        ebs: true
