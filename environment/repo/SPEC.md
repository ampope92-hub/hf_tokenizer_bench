# Report specification

The tool takes one argument, the cases directory, and prints one line of JSON to stdout.

## Reading the cases

Take every file in the given directory whose name ends in `.json` and process them in
ascending, case-sensitive filename order. Each case is an object with:

- `name`
- `model` — the Hugging Face repo id whose tokenizer to load, e.g. `bert-base-uncased`
- `revision` — the commit hash of that repo to load the tokenizer at. Load exactly this
  revision rather than the repo's default branch; the report has to stay the same when the
  branch moves.
- `text_a`, and optionally `text_b`. Encode as a pair when `text_b` is present, single
  otherwise.
- `add_special_tokens` — bool, passed straight through to the encode call
- `max_length` — optional. Enable truncation with this max length, stride 0, direction right,
  and strategy from `truncation`: `"longest_first"` (the default when `truncation` is absent),
  `"only_first"`, or `"only_second"`. No `max_length` means truncation off.
- `padding` — optional integer. Enable fixed-length padding to exactly that length, direction
  right, pad id 0, pad type id 0, pad token `"[PAD]"`. Absent means padding off.
- `fertility_pass` and `fertility_warn` — finite numbers, the thresholds for the status below.

One case's truncation and padding settings must not leak into the next case.

## Per-case encoding fields

From the encoding, report `n_tokens` (the number of token ids), `ids`, `tokens`, `type_ids`,
`attention_mask`, `special_tokens_mask`, and `offsets` (each offset a two-element
`[start, end]` array).

## Per-case analysis fields

A *content token* is a token whose word id is non-null. This excludes special tokens and
padding. A *word* is a distinct (sequence id, word id) pair over the content tokens. Sequence
id distinguishes `text_a` from `text_b` in a pair, so word 0 of the first text and word 0 of
the second are different words.

- `content_tokens` — the number of content tokens.
- `word_count` — the number of words.
- `split_words` — the number of words carrying two or more tokens.
- `max_word_tokens` — the largest number of tokens carried by any single word, or `0` when
  there are no words.
- `fertility` — `content_tokens / word_count`, or `null` when `word_count` is `0`.
- `compression` — total input characters divided by `content_tokens`, or `null` when
  `content_tokens` is `0`. Total input characters is the number of Unicode scalar values in
  `text_a`, plus those in `text_b` when present.
- `status` — classify the **unrounded** fertility with inclusive upper bounds, pass before
  warn: `"pass"` if fertility <= `fertility_pass`, else `"warn"` if fertility <=
  `fertility_warn`, else `"fail"`. When fertility is `null` the status is `"pass"`.

## Rounding

Every float in the report (`fertility`, `compression`, and `corpus_fertility` below) is rounded
to exactly six decimal places, rounding halves away from zero: compute
`floor(x * 1e6 + 0.5) / 1e6` on the raw value. All these values are non-negative. Only the
reported value is rounded; the status classification above uses the raw value.

## The report

One JSON object on one line, `{"cases": [...], "summary": {...}}`.

Each case object has exactly the keys `name`, `model`, `n_tokens`, `ids`, `tokens`, `type_ids`,
`attention_mask`, `special_tokens_mask`, `offsets`, `content_tokens`, `word_count`,
`split_words`, `max_word_tokens`, `fertility`, `compression`, `status`, and the cases appear in
input order in the `cases` array.

The `summary` has exactly `case_count` (files processed), `total_tokens` (sum of `n_tokens`),
`total_content_tokens` and `total_words` (sums over cases), `corpus_fertility`
(`total_content_tokens / total_words` computed from those totals, not an average of the
per-case fertilities, and `null` when `total_words` is `0`), and `pass`, `warn`, `fail` (how
many cases got each status).

With no matching files, emit an empty `cases` array, zero counts, and a `null` corpus
fertility.
