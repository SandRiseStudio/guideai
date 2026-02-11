#!/bin/sh
# Auto-detect DNS resolver from container's resolv.conf
# Docker uses 127.0.0.11, Podman uses network gateway (e.g., 10.89.0.1)
set -e

# Extract first nameserver from resolv.conf
NGINX_RESOLVER=$(grep -m1 '^nameserver' /etc/resolv.conf | awk '{print $2}')

# Fallback to Docker DNS if not found
NGINX_RESOLVER="${NGINX_RESOLVER:-127.0.0.11}"

echo "Using DNS resolver: $NGINX_RESOLVER"

# Export for envsubst
export NGINX_RESOLVER

# Run envsubst on template to generate actual nginx.conf
envsubst '$NGINX_RESOLVER' < /etc/nginx/templates/nginx.conf.template > /etc/nginx/nginx.conf

# Start nginx
exec nginx -g 'daemon off;'
