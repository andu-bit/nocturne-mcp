#!/bin/bash
# Pre-start script for nocturne-sse
# Backs up config.json and sets port to 8234 for SSE server
set -e

cd /root/nocturne_memory

# Backup
cp config.json config.json.sse

# Set SSE port using Python
python3 -c "
import json
with open('config.json', 'r') as f:
    c = json.load(f)
c['web_port'] = 8234
with open('config.json', 'w') as f:
    json.dump(c, f, indent=2)
"

echo "Config prepared for SSE on port 8234"
