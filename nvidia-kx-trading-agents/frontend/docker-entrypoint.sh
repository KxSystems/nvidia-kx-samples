#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Substitute only INFERENCE_ORIGIN in nginx config template
# This avoids replacing nginx's built-in variables like $uri, $host, etc.
envsubst '${INFERENCE_ORIGIN}' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf

# Start nginx
exec nginx -g 'daemon off;'
