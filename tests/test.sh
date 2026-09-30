#!/bin/bash

# Verifier entrypoint. This runs in the verifier container, not the agent's — it sees only the
# paths declared in `artifacts`. All tooling is baked into tests/Dockerfile; nothing is
# installed or fetched here except the tokenizer models the report is checked against, which
# come from the Hub at grade time (this task is internet-enabled by design).

set -uo pipefail

mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt

# This shell's own process group. Each run below is started under `setsid` so it gets a group
# of its own that can be torn down as a unit, but /proc can be read in the window before
# setsid(2) has taken effect, and in that window it still reports THIS group. Killing that
# group kills the verifier itself: the log stops mid-script, pytest never runs, no ctrf.json
# is written and the reward stays 0. Three rounds were lost to exactly that before the cause
# was found, so no group is ever signalled unless it is demonstrably not our own.

# The graded report must come out of the agent's own crate, so it is rebuilt from the
# collected sources and run here. The dependency tree is already compiled into this image, so
# only the agent's own sources recompile.
#
# That rebuild executes code the agent wrote, so it runs as the unprivileged `runner`. Artifacts
# land owned by root, so hand the crate over first. /logs is left alone — Harbor owns it and the
# reward is written there last, after every agent process is dead.
chown -R runner:runner /app/repo /app/cases

# Everything below that touches agent-authored code runs through this helper: the build user,
# with supplementary groups cleared and no-new-privileges set, so an inherited group or a
# setuid binary cannot widen what that code can reach.
as_runner() {
  setpriv --clear-groups --no-new-privs --reuid runner --regid runner "$@"
}

# The shipped tests/ directory lands here at runtime, so the verifier's own code sits under
# /tests just as agent-authored code is about to run. Close the whole directory to the build
# user first: root still reads it, `runner` cannot even traverse it. If it is still reachable
# the run is abandoned with reward 0 rather than graded — a reachable /tests is one whose test
# file the agent's code can rewrite before pytest reads it.
#
# There is no answer key to protect: test_outputs.py recomputes the expected report with the
# Python tokenizers library, so nothing on disk holds the right answers. The hidden CASES are
# inputs the crate must tokenize and live at /opt/hidden_cases, deliberately readable.
chmod 700 /tests 2>/dev/null || true
if as_runner bash -c 'test -r /tests/test_outputs.py' 2>/dev/null; then
  echo "FATAL: /tests is still reachable by the unprivileged build user; the verifier's own"
  echo "code can be rewritten by agent-authored code, so this run cannot be graded."
  echo 0 > /logs/verifier/reward.txt
  exit 0
fi
echo "verifier files closed to the unprivileged build user"

# Harbor uploads the agent's sources with whatever mtime they carried in its container, which
# can predate this image's own layers. Cargo decides freshness by mtime, so an older source
# silently counts as "already built" — stamp the collected sources to now so the rebuild is
# unconditional. Belt and braces with the `cargo clean -p` in tests/Dockerfile.
find /app/repo/src -type f -exec touch {} + 2>/dev/null

# run_report <output-path> <cases-dir>
#
# Runs the agent's runner in its own session, so every process it spawns shares one process
# group that can be torn down as a unit: a double-forked child left alive would still be around
# during grading, where it could rewrite the captured report or the reward. stdout is captured
# to a root-owned file and pytest reads that — running the crate from inside pytest would
# execute agent code as root in the container that decides the reward. stderr is deliberately
# NOT redirected: it flows to the verifier log, where a build failure is readable instead of
# looking like an empty report.
run_report() {
  local out="$1" cases="$2"
  local pid pgid
  # setpriv preserves the environment, so without this HOME is still root's and the crate's
  # first Hub download dies with PermissionDenied writing the cache — which looks like a build
  # failure but is not. Point HOME and the HF cache at the build user's own directory.
  setsid \
    env HOME=/home/runner \
        HF_HOME=/home/runner/.cache/huggingface \
        XDG_CACHE_HOME=/home/runner/.cache \
    setpriv --clear-groups --no-new-privs --reuid runner --regid runner \
    bash /app/repo/run.sh "$cases" > "$out" &
  pid=$!
  wait "$pid"
  echo "run.sh on $cases exit status: $?"
  # `setsid` makes the launched process a session leader, and a session leader's process group
  # id is its own pid, so the group is addressed directly as -"$PID". The previous version read
  # the group id back out of /proc instead, which races setsid(2): in the window before it takes
  # effect /proc still reports the child in THIS shell's group, and the kill then took down the
  # verifier itself -- silently, with no pytest output and the reward left at 0.
  kill -TERM -- -"$pid" 2>/dev/null || true
  kill -KILL -- -"$pid" 2>/dev/null || true
  as_runner bash -c 'kill -9 -1' 2>/dev/null || true
  chown root:root "$out" 2>/dev/null || true
  chmod 600 "$out" 2>/dev/null || true
}

# The shipped sample cases, twice — the second run is what the byte-identical check compares
# against, and it has to be a genuinely separate invocation rather than the same bytes read
# twice. Then the hidden cases, which exercise the conventions the sample does not reach.
run_report /opt/report_sample.json        /app/cases
run_report /opt/report_sample_repeat.json /app/cases
run_report /opt/report_hidden.json        /opt/hidden_cases

# Nothing the agent started may be alive while pytest runs or while the reward is written.
as_runner bash -c 'kill -9 -1' 2>/dev/null || true

# -P keeps the working directory (/app, per the Dockerfile's WORKDIR) off sys.path. The crate
# runs as `runner` and writes into /app, so without this it can drop an /app/pytest.py holding
# sys.exit(0); `python -m pytest` would import that no-op, exit 0, and bypass the whole suite
# for reward 1. The test file and cache are addressed absolutely either way.
python -P -m pytest -o cache_dir=/tmp/pytest_cache \
  --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
exit_code=$?
if [ "$exit_code" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi

# Harbor grades from reward.txt, never from this script's exit status.
exit 0
