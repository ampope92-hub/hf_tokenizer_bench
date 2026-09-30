# Source the Rust toolchain from the canonical rust image (the agent builds a Cargo project).
FROM public.ecr.aws/docker/library/rust:1.85-slim@sha256:9f841bbe9e7d8e37ceb96ed907265a3a0df7f44e3737d0b100e7907a679acb36 AS rust

# Harbor's harness needs tmux and asciinema, so the final image is the canonical Python base
# with the Rust toolchain copied in.
FROM public.ecr.aws/docker/library/python:3.13-slim-bookworm@sha256:01f42367a0a94ad4bc17111776fd66e3500c1d87c15bbd6055b7371d39c124fb

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tmux \
        asciinema \
        gcc \
        g++ \
        pkg-config \
        libssl-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rust toolchain (cargo/rustc + std) from the rust stage.
COPY --from=rust /usr/local/cargo /usr/local/cargo
COPY --from=rust /usr/local/rustup /usr/local/rustup

# No Python packages are installed here. The task is a Rust binary and the agent never
# touches Python; pytest, pytest-json-ctrf and the Python tokenizers stack that computes the
# expected report belong to the verifier image and live only in tests/Dockerfile.

# The Cargo project the agent completes, and the sample cases.
COPY repo /app/repo
COPY cases /app/cases

WORKDIR /app
