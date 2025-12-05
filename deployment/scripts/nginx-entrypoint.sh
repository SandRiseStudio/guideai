#!/bin/sh
# GuideAI nginx entrypoint that safely renders the target config before startup
set -eu

TEMPLATE_PATH="${NGINX_TEMPLATE_PATH:-/etc/nginx/nginx.conf.template}"
TARGET_PATH="${NGINX_TARGET_PATH:-/etc/nginx/nginx.conf}"
TEMPLATE_VARS="${NGINX_TEMPLATE_VARS:-GUIDEAI_STAGING_UPSTREAM_HOST GUIDEAI_STAGING_UPSTREAM_PORT}"

if [ ! -f "$TEMPLATE_PATH" ]; then
    echo "nginx template not found at $TEMPLATE_PATH" >&2
    exit 1
fi

TRIMMED_VARS="$(printf %s "$TEMPLATE_VARS" | tr -d '[:space:]')"

if [ -n "$TRIMMED_VARS" ]; then
    VAR_PATTERN=""
    for VAR_NAME in $TEMPLATE_VARS; do
        eval "VAR_VALUE=\${$VAR_NAME:-}"
        if [ -z "$VAR_VALUE" ]; then
            echo "Environment variable $VAR_NAME must be set for nginx templating" >&2
            exit 1
        fi
        VAR_PATTERN="$VAR_PATTERN\${$VAR_NAME} "
    done
    envsubst "$VAR_PATTERN" < "$TEMPLATE_PATH" > "$TARGET_PATH"
else
    cp "$TEMPLATE_PATH" "$TARGET_PATH"
fi

exec nginx -g 'daemon off;'
