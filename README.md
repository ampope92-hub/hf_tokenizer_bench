# Hugging Face Tokenizer Benchmark

The agent finishes a Rust CLI, `hf_tokenize`, in a Cargo project stub at `/app/repo` that already depends on the `tokenizers` crate. The tool takes a directory of JSON test cases and, for each case, loads a Hugging Face tokenizer from the Hub at a pinned commit. It applies the case's truncation and padding settings, encodes single or pair input, and prints a single-line JSON report. The report contains the raw encoding fields (ids, tokens, type ids, masks, offsets) and a computed analysis layer on top: word counts, split words, fertility, compression, a pass/warn/fail status, and corpus-level summary statistics. The exact report format is in `/app/repo/SPEC.md`, and output must be byte-identical across runs.

## What makes it hard

The crate handles the encoding itself. The difficulty is the computed layer, where four conventions each fail silently when implemented one plausible step wrong:

- **Words are `(sequence_id, word_id)` pairs.** In a pair encoding, word 0 of text A and word 0 of text B are different words. Grouping on `word_id` alone merges the two segments and corrupts `word_count`, `split_words`, `max_word_tokens` and fertility, but only on pair cases. Getting it right means reaching for `get_sequence_ids`.
- **Rounding is six decimals, half away from zero** (`floor(x*1e6+0.5)/1e6`). Rust's `{:.6}` formatting and Python's `round()` both round half to even. A hidden case sits on an exact binary tie: 128 single-token words over 257 characters gives compression 2.0078125, which should round to 2.007813, not 2.007812.
- **Status classifies the raw fertility, not the rounded one.** A hidden case has fertility 4/3 against a pass threshold of 1.333333. Classifying the rounded value flips it from warn to pass.
- **Content tokens have a non-null word id.** That excludes padding as well as special tokens, and the empty-text case must yield `null` fertility and compression rather than zero or NaN.

On top of that, the output must match exactly across truncation strategies (`longest_first`, `only_first`, `only_second`), fixed padding, `add_special_tokens` on and off, and four tokenizer families including byte-level BPE.

## How it's graded

The verifier runs in a separate container. It copies the agent's crate sources onto a skeleton whose dependency tree is already compiled, then rebuilds and runs the agent's code from clean. A hand-written report therefore never reaches the grader.

There is no golden output file. `tests/test_outputs.py` computes the expected report independently with the Python `tokenizers` library, which wraps the same Rust core, so there is no answer on disk to copy. The hidden cases are inputs only, and they exercise the conventions above.

The suite runs ten checks:

- The runner and the source file exist.
- The full report matches exactly on the sample cases.
- The full report matches exactly on the hidden cases.
- Output is byte-identical across two separate invocations.
- Five targeted checks: `(sequence, word)` grouping on a pair, padding excluded from content tokens, half-away-from-zero rounding on the tie case, status from raw fertility on the threshold case, and corpus fertility taken from totals rather than averaged.

The agent's code builds and runs as an unprivileged user with groups cleared. Its process groups are torn down before the reward is written, `/tests` is closed to it, and pytest runs with `-P` so a planted module cannot shadow it.

Every case pins a tokenizer commit hash, both Docker bases are pinned by digest, the verifier's Python dependencies are pinned by hash, and `Cargo.lock` is frozen against Rust 1.85. Both the agent and verifier phases need network access to reach the Hub.

## Repository layout

- `instruction.md`: the task prompt given to the agent.
- `task.toml`: metadata, difficulty, solution and verification notes, and resource limits.
- `environment/`: the agent's container (`Dockerfile`), the Cargo stub with `SPEC.md` and `run.sh` (`repo/`), and three sample cases (`cases/`).
- `solution/`: `solve.sh` and the reference implementation (`main.rs`).
- `tests/`: verifier image and entrypoint (`Dockerfile`, `test.sh`), pytest checks with the independent Python reference (`test_outputs.py`, `requirements.lock`), the prebuilt crate skeleton (`skeleton/`) and nine hidden cases (`hidden_cases/`).

## Running it

Requires Docker and Harbor (`uv tool install harbor` or `pip install harbor`). From the repo root:

```
harbor run -p . -a oracle
```

This runs the reference solution through the verifier and should score reward 1. To try an agent instead:

```
harbor run -p . -a <agent> -m <model>
```

For example, `-a claude-code`.

---

Task design, data generators, reference solution and verifier by Audrey Pope.
