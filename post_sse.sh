#!/bin/bash
# Post-stop script for nocturne-sse
# Restores original config.json
set -e

cd /root/nocturne_memory

if [ -f config.json.sse ]; then
    cp config.json.sse config.json
    rm -f config.json.sse
    echo "Config restored from backup"
fi
