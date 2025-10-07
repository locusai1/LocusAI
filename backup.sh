#!/bin/bash
# Backup script for dentist-ai project

# Timestamp for unique filename
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")

# Output file
BACKUP_FILE="backup_$TIMESTAMP.zip"

# Files/folders to include
zip -r $BACKUP_FILE \
  adapters \
  businesses \
  core \
  logs \
  templates \
  dashboard.py \
  main.py \
  receptionist.db \
  view_logs.py \
  view_logs_db.py

echo "✅ Backup complete: $BACKUP_FILE"

