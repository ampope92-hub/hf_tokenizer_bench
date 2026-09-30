"""Behavioral verifier for the hf_tokenize benchmark.

The agent implements a Rust binary that runs Hugging Face tokenizers over a directory of
cases and prints an exact JSON report, including computed word-level analysis (content
tokens, (sequence, word) grouping, fertility/compression with null conventions, six-decimal
half-away-from-zero rounding, raw-value threshold classification, and totals-based corpus
fertility). We compute the expected report *independently* with the Python `tokenizers`
library (the same core engine as the Rust crate, so encodings match bit-for-bit) — nothing
is shipped as a golden file the agent could echo. Checks run on the shipped sample cases
and on a hidden set exercising the rest of the conventions.
"""
import glob
import json
import math
import os
import pathlib

from tokenizers import Tokenizer

APP = "/app"
# The hidden cases are INPUTS, not answers — the crate has to tokenize them, so they sit at a
# path it can read. There is no golden output anywhere: the expected report is computed here,
# independently, with the Python tokenizers library.
HIDDEN = "/opt/hidden_cases"

# test.sh runs the agent's binary (as the unprivileged build user, never as root) and captures
# its stdout to these root-owned files. pytest reads them rather than invoking agent code
# itself — running the crate from inside pytest would execute it as root in the container that
# decides the reward.
REPORT_SAMPLE = "/opt/report_sample.json"
REPORT_HIDDEN = "/opt/report_hidden.json"
REPORT_SAMPLE_REPEAT = "/opt/report_sample_repeat.json"

_CACHE = {}


def _tok(model, revision):
    """The tokenizer for a case, at the exact commit the case names.

    Pinned rather than tracking each repo's default branch: the expected report is computed
    here and the agent's is computed in its own process, so both have to be reading the same
    tokenizer files however the Hub moves.
    """
    key = (model, revision)
    if key not in _CACHE:
        _CACHE[key] = Tokenizer.from_pretrained(model, revision=revision)
    return _CACHE[key]


def _round6(x):
    # round half away from zero at six decimals (values are non-negative)
    return math.floor(x * 1e6 + 0.5) / 1e6


def _expected(cases_dir):
    """Compute the correct report for a directory of case files, independently."""
    files = sorted(glob.glob(os.path.join(cases_dir, "*.json")))
    cases = []
    total = total_content = total_words = 0
    npass = nwarn = nfail = 0
    for path in files:
        with open(path, encoding="utf-8") as handle:
            c = json.load(handle)
        tok = _tok(c["model"], c["revision"])
        if c.get("max_length") is not None:
            tok.enable_truncation(max_length=int(c["max_length"]),
                                  strategy=c.get("truncation") or "longest_first",
                                  direction="right")
        else:
            tok.no_truncation()
        if c.get("padding"):
            tok.enable_padding(length=int(c["padding"]), direction="right",
                               pad_id=0, pad_type_id=0, pad_token="[PAD]")
        else:
            tok.no_padding()
        add = c.get("add_special_tokens", True)
        enc = tok.encode(c["text_a"], c.get("text_b"), add_special_tokens=add)

        groups = {}
        content = 0
        for i, w in enumerate(enc.word_ids):
            if w is not None:
                content += 1
                s = enc.sequence_ids[i] or 0
                groups[(s, w)] = groups.get((s, w), 0) + 1
        word_count = len(groups)
        split_words = sum(1 for n in groups.values() if n >= 2)
        max_word_tokens = max(groups.values(), default=0)

        chars = len(c["text_a"]) + (len(c["text_b"]) if c.get("text_b") is not None else 0)
        raw_fert = (content / word_count) if word_count else None
        compression = _round6(chars / content) if content else None

        if raw_fert is None or raw_fert <= c["fertility_pass"]:
            status = "pass"
            npass += 1
        elif raw_fert <= c["fertility_warn"]:
            status = "warn"
            nwarn += 1
        else:
            status = "fail"
            nfail += 1

        total += len(enc.ids)
        total_content += content
        total_words += word_count
        cases.append({
            "name": c["name"], "model": c["model"], "n_tokens": len(enc.ids),
            "ids": list(enc.ids), "tokens": list(enc.tokens), "type_ids": list(enc.type_ids),
            "attention_mask": list(enc.attention_mask),
            "special_tokens_mask": list(enc.special_tokens_mask),
            "offsets": [list(o) for o in enc.offsets],
            "content_tokens": content, "word_count": word_count,
            "split_words": split_words, "max_word_tokens": max_word_tokens,
            "fertility": _round6(raw_fert) if raw_fert is not None else None,
            "compression": compression, "status": status,
        })
    corpus = _round6(total_content / total_words) if total_words else None
    return {"cases": cases, "summary": {
        "case_count": len(files), "total_tokens": total,
        "total_content_tokens": total_content, "total_words": total_words,
        "corpus_fertility": corpus, "pass": npass, "warn": nwarn, "fail": nfail,
    }}


_REPORTS = {f"{APP}/cases": REPORT_SAMPLE, HIDDEN: REPORT_HIDDEN}


def _report_raw(path):
    assert os.path.isfile(path), (
        f"{path} is missing — `bash /app/repo/run.sh <cases-dir>` produced no report when the "
        "verifier ran it. It must build the crate and print the JSON report to stdout."
    )
    lines = [ln for ln in pathlib.Path(path).read_text().strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _run_raw(cases_dir):
    return _report_raw(_REPORTS[cases_dir])


def _run(cases_dir):
    return json.loads(_run_raw(cases_dir))


def _find(report, name):
    for case in report["cases"]:
        if case["name"] == name:
            return case
    raise AssertionError(f"no case named {name} in {[c['name'] for c in report['cases']]}")


# ------------------------------------------------------------------ structural
def test_runner_exists():
    """The runner script the report is produced through is present."""
    assert os.path.isfile(f"{APP}/repo/run.sh")


def test_source_exists():
    """The crate source the verifier rebuilds from is present."""
    assert os.path.isfile(f"{APP}/repo/src/main.rs")


# ------------------------------------------------- full-report exact matches
def test_sample_report_matches():
    """The full report matches an independent implementation on the shipped sample cases."""
    assert _run(f"{APP}/cases") == _expected(f"{APP}/cases"), (
        "the report must match the reference exactly on the sample cases"
    )


def test_hidden_report_matches():
    """The full report matches on cases the agent never saw, covering the conventions the sample does not reach."""
    assert _run(HIDDEN) == _expected(HIDDEN), (
        "the report must match on the hidden cases — a solution that only handled the "
        "sample's conventions disagrees here"
    )


def test_output_is_byte_identical_across_runs():
    """Two separate invocations over the same cases print exactly the same bytes."""
    assert _report_raw(REPORT_SAMPLE) == _report_raw(REPORT_SAMPLE_REPEAT), (
        "repeated runs must be byte-identical — map iteration order or unstable float "
        "formatting will show up here"
    )


# ------------------------------------------------- targeted convention checks
def test_word_grouping_uses_sequence_ids():
    """In a pair encoding, word 0 of each segment is a distinct word — grouping on word_id alone merges them."""
    # In a pair, word 0 of text_a and word 0 of text_b are DIFFERENT words.
    exp = _expected(f"{APP}/cases")
    got = _find(_run(f"{APP}/cases"), "bert_pair")
    want = _find(exp, "bert_pair")
    for key in ("content_tokens", "word_count", "split_words", "max_word_tokens"):
        assert got[key] == want[key], f"{key}: {got[key]} != {want[key]}"


def test_padding_not_counted_as_content():
    """Padding tokens carry null word ids and are not content tokens."""
    got = _find(_run(HIDDEN), "distilbert_pad")
    want = _find(_expected(HIDDEN), "distilbert_pad")
    assert got["content_tokens"] == want["content_tokens"], (
        "padding tokens have null word ids and are not content tokens"
    )


def test_rounding_is_half_away_from_zero():
    """Six-decimal rounding goes half away from zero, which only shows on an exact binary tie."""
    # The tie case is engineered so half-to-even (Rust's {:.6} formatting) differs.
    got = _find(_run(HIDDEN), "tie_case")
    want = _find(_expected(HIDDEN), "tie_case")
    assert got["compression"] == want["compression"], (
        f"compression must round halves away from zero: {got['compression']} != {want['compression']}"
    )


def test_status_uses_raw_not_rounded():
    """Status classifies the raw fertility; classifying the rounded value flips the engineered boundary case."""
    got = _find(_run(HIDDEN), "threshold_case")
    want = _find(_expected(HIDDEN), "threshold_case")
    assert got["status"] == want["status"], (
        "status classifies the RAW fertility; classifying the rounded value flips this case"
    )


def test_corpus_fertility_from_totals():
    """Corpus fertility comes from the totals, not from averaging the per-case values."""
    got = _run(HIDDEN)["summary"]
    want = _expected(HIDDEN)["summary"]
    assert got["corpus_fertility"] == want["corpus_fertility"], (
        "corpus fertility is total_content/total_words, not the mean of per-case fertilities"
    )
    for key in ("pass", "warn", "fail", "total_content_tokens", "total_words"):
        assert got[key] == want[key], f"summary {key}: {got[key]} != {want[key]}"
