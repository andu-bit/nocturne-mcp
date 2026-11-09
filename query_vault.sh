#!/bin/bash
# Query the godcode vault database
# Usage: ./query_vault.sh [sql]
# Example: ./query_vault.sh "SELECT path FROM paths LIMIT 10"
DB="/root/nocturne_memory/godcode_vault.db"
if [ -z "$1" ]; then
    sqlite3 "$DB" "SELECT uri FROM search_documents ORDER BY priority LIMIT 20"
else
    sqlite3 "$DB" "$1"
fi
