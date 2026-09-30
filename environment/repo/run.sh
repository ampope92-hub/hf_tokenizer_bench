#!/usr/bin/env bash
# Build and run the tokenizer benchmark. Prints the JSON report to stdout.
#   bash /app/repo/run.sh <cases-dir>
set -euo pipefail
cd /app/repo
cargo build --release --quiet
exec ./target/release/hf_tokenize "$@"
