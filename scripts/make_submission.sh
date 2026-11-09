#!/usr/bin/env bash
# Builds dist/submission.zip: root-level .py modules and requirements.txt only,
# as the platform copies nothing else.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p dist
rm -f dist/submission.zip
zip -q -j dist/submission.zip ./*.py requirements.txt
unzip -l dist/submission.zip
