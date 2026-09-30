#!/usr/bin/env bash
set -euo pipefail

# Reference implementation of the tokenizer benchmark. Reads every *.json case (sorted,
# case-sensitive), builds each case's Hugging Face tokenizer at the commit the case names,
# applies its truncation and padding settings, encodes, and reports both the raw encoding
# fields and the computed word-level analysis: content tokens are tokens with a non-null word
# id; words are distinct (sequence id, word id) pairs; fertility = content/word, compression =
# chars/content, with null conventions on zero denominators; floats rounded to 6 decimals
# half-away-from-zero via floor(x*1e6+0.5)/1e6; status classifies the RAW fertility with
# inclusive upper bounds (pass <= fertility_pass, warn <= fertility_warn, else fail; null
# fertility -> pass); the summary's corpus fertility comes from the totals, not from averaging
# per-case values.

# The implementation is solution/main.rs, next to this script — Rust is not a shell language
# and a hundred lines of it inside a heredoc is neither reviewable nor compilable on its own.
install -m 644 "$(dirname "$0")/main.rs" /app/repo/src/main.rs

cd /app/repo
cargo build --release --quiet
echo "oracle build ok"
