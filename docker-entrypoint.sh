#!/bin/sh

/usr/local/bin/gtfs-upcoming \
    --port=6824 \
    --promport=6825 \
    --config="/gtfs/config.ini" \
    --gtfs="/gtfs" \
    --provider="${GTFS_PROVIDER}" \
    --env="${GTFS_ENVIRONMENT}"