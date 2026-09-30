# Verifier image. Runs in its own container: it never sees the agent's filesystem, only the
# paths declared in `artifacts`. It rebuilds the agent's crate from source and runs it, so it
# needs the Rust toolchain, and it computes the expected report itself with the Python
# tokenizers library, so it needs that too.

FROM public.ecr.aws/docker/library/rust:1.85-slim@sha256:9f841bbe9e7d8e37ceb96ed907265a3a0df7f44e3737d0b100e7907a679acb36 AS rust

FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# libssl-dev/pkg-config are not optional: the tokenizers crate's `http` feature pulls
# openssl-sys, which fails the build with "OPENSSL_DIR unset" in the slim image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        pkg-config \
        libssl-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup

# Verifier tooling, hash-pinned: pytest and pytest-json-ctrf to run and report the suite, and
# the Python `tokenizers` + huggingface-hub stack that computes the expected report. Nothing is
# installed at trial time. The import check keeps a lockfile edit from silently dropping one.
COPY requirements.lock /tmp/requirements.lock
RUN python -m pip install --require-hashes --no-deps --no-cache-dir -r /tmp/requirements.lock
RUN python -c "import pytest, ctrf, tokenizers"

# test.sh rebuilds and runs the agent's crate, so agent-authored code executes in this image.
# That code runs as `runner`, never root: runner owns the crate and the cargo cache, nothing else.
RUN useradd --create-home --uid 10001 --shell /bin/bash runner

# The crate skeleton mirrors environment/repo's manifest so the dependency tree — tokenizers,
# onig, the http stack — is fetched and compiled now, while the build still has a network. The
# agent's own src/, Cargo.toml and Cargo.lock arrive later as artifacts and overwrite these,
# leaving only the crate's own sources to recompile. Keep in sync with environment/repo.
COPY skeleton /app/repo
# The prebuilt skeleton binary must NOT survive into the image: cargo decides freshness by
# mtime, and Harbor uploads the agent's sources with whatever mtime they carried, which can
# predate this layer. `cargo clean -p` drops just this crate's artifacts and keeps the
# compiled dependency tree, which is the whole point of the skeleton.
RUN cd /app/repo \
    && cargo fetch --locked \
    && cargo build --release --offline \
    && cargo clean --release -p hf_tokenize \
    && rm -rf /app/repo/src

# Artifact landing directories must exist before Harbor uploads the declared artifacts.
RUN mkdir -p /app/repo/src /app/cases

# The crate runs as runner and cargo writes target/ and the CARGO_HOME package-cache lock;
# neither holds anything secret. /app is runner-owned so the build can write there.
RUN chown -R runner:runner /app /usr/local/cargo \
    && chmod 1755 /app

# The crate downloads tokenizers from the Hub at grade time and caches them under HOME, which
# test.sh points here. Pre-create it so the first write does not race the directory creation.
RUN mkdir -p /home/runner/.cache/huggingface \
    && chown -R runner:runner /home/runner

# The hidden cases are INPUTS the crate must tokenize, not answers — there is no golden output
# in this task at all, because test_outputs.py recomputes the expected report with the Python
# tokenizers library. So they are world-readable at a path outside the /tests mount, which
# test.sh closes to the build user before any agent code runs.
COPY hidden_cases /opt/hidden_cases
RUN chmod -R a+rX /opt/hidden_cases

COPY . /tests/

WORKDIR /app
