#!/usr/bin/with-contenv bashio
export ANTHROPIC_API_KEY="$(bashio::config 'anthropic_api_key')"
export ANTHROPIC_MODEL="$(bashio::config 'anthropic_model')"
export HOMEBOX_URL="$(bashio::config 'homebox_url')"
export HOMEBOX_PUBLIC_URL="$(bashio::config 'homebox_public_url')"
export HOMEBOX_USERNAME="$(bashio::config 'homebox_username')"
export HOMEBOX_PASSWORD="$(bashio::config 'homebox_password')"
export HOMEBOX_LOCATION_ID="$(bashio::config 'homebox_location_id')"
export PORT=8099
cd /app
exec gunicorn --bind 0.0.0.0:8099 --workers 2 --timeout 120 server:app
