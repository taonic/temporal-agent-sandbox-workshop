# Instruqt

The lab prose and the lifecycle scripts live in [`challenges/`](../challenges), not
here. Instruqt gets a generated copy of the prose and thin wrappers that run the
repo's own scripts inside the sandbox. Which command ships a change depends on what
you changed, and most of the time it's none of them:

| What you changed | What ships it |
|---|---|
| A `challenges/NN/*.sh` script, a test it runs, `solutions/`, or anything learners type against | Merge to the branch `WORKSHOP_REF` names. Nothing here. |
| A `challenges/NN/assignment.md` | `uv run python scripts/build_track.py`, then `instruqt track push` |
| `track/track.yml` | `instruqt track push` |
| `sandbox/config.yml` or `sandbox/scripts/*` | `instruqt sandbox push` **and** `publish` |
| `bin/write-env` | Merge. It runs from the clone. |

The first row matters most. The sandbox clones the repo at `WORKSHOP_REF` when it
starts, and every challenge's `setup`/`check`/`solve`/`cleanup` is a wrapper that
calls `$WORKDIR/challenges/NN/<verb>.sh` in that clone. So a fix to a check reaches
the next learner as soon as it's on that branch.

## Layout, and where each command runs

```
instruqt/
  track/     track.yml + NN-slug/       -> run `instruqt track *` from here
  sandbox/   config.yml + scripts/      -> run `instruqt sandbox *` from here
  bin/       write-env. Not pushed: runs inside the sandbox, from the clone
```

Both CLIs read their config from `$PWD`, so run them from `track/` or `sandbox/`,
not from `instruqt/`.

`track/NN-slug/` is **generated** by `scripts/build_track.py` from
`challenges/NN-slug/`: `assignment.md` is copied verbatim and `<verb>.sh` becomes
`<verb>-workstation`. Don't edit those files; edit `challenges/` and rebuild.

The `-workstation` suffix (on `sandbox/scripts/setup-workstation` and on every
challenge script) is the VM's `name` in `sandbox/config.yml`, and every tab says
`hostname: workstation`. If you rename the VM, all three have to change together.

## What the sandbox contains

`sandbox/scripts/setup-workstation` runs once when a sandbox starts:

- uv and the Temporal CLI (pinned), and Ollama with `LLM_MODEL` pulled and warmed
- the whole repo cloned at `/root/workshop`, then `uv sync` and a fresh dataset
- systemd services for the Temporal dev server (UI on 8233) and the Max app (8000)
- `/etc/workshop/env` (PATH, `WORKDIR`), sourced by every terminal and every challenge script

It **doesn't** start the worker. Learners start it in challenge 1 and kill and
restart it in challenge 2.

It clones the whole repo, not an allow-list like the platform workshop uses,
because `challenges/lib.sh` catches a learner up by copying `solutions/chNN/` and
the Solve button does the same. So the answer key is in the checkout on purpose.

## The `.env`, and why it's written twice

The app, the worker and the checks all read `/root/workshop/.env`.
`bin/write-env` writes it, and it runs twice: once from the sandbox setup and
again at the start of every challenge setup.

That's because of something the platform workshop learned the hard way:
**the `environment:` block in `sandbox/config.yml` isn't in scope for the setup
script.** It goes to a learner's shell. The participant id and sandbox id may not
reach the setup script either. Challenge lifecycle scripts run later, in a
different context. So `write-env` takes each value from wherever it shows up, and
an empty value never overwrites one already in `.env`:

| `.env` key | Taken from |
|---|---|
| `DAYTONA_API_KEY` | `$DAYTONA_API_KEY`, else the cloned `sandbox/config.yml` |
| `LLM_MODEL` | `$LLM_MODEL`, else the cloned `sandbox/config.yml` |
| `LEARNER_ID` | `$INSTRUQT_PARTICIPANT_ID`, lowercased and cut to 12 chars |
| `TEMPORAL_UI_URL` | `$_SANDBOX_ID`, as `https://workstation-8233-<id>.env.play.instruqt.com` |

If `.env` changes, it restarts the Max app.

For the same reason, the setup script defaults `WORKSHOP_REPO`, `WORKSHOP_REF` and
`WORKDIR` itself, since it needs them before there's a checkout to read. After
the clone it asserts they match `sandbox/config.yml`. **Changing `WORKSHOP_REF` in
`config.yml` alone fails the setup on purpose.** Change both.

## The Daytona key

`DAYTONA_API_KEY` is a plain variable in `sandbox/config.yml`, not an Instruqt
secret. One org key is shared by every learner, and the org needs Tier 2 or
higher (see [DESIGN.md](../DESIGN.md)).

The committed value is the placeholder `"<org-key>"`, which `write-env` treats as
unset. There are two ways to supply the real one:

- **Put it in the copy you push, but don't commit it.** That works only if
  Instruqt's environment block reaches the setup or challenge scripts, which hasn't
  been proven yet. The cloned `config.yml` will still hold the placeholder.
- **Commit it.** That definitely works, because `write-env` reads it from the
  clone. But the repo then holds a live key, and rotating it is the only control.

Until one of these has been proven on a real run, check the first `track test`
for `warn: no DAYTONA_API_KEY reached this sandbox`.

## First time on a machine

```bash
brew install instruqt/tap/instruqt
instruqt auth login
instruqt config list          # team = temporal
```

## The first push, in this order

The track names `sandbox_preset: temporal-agent-sandbox-workshop`, and
`track validate` and `track push` both look up that preset before anything else.
Until it exists they fail with
`failed to remote config (temporal-agent-sandbox-workshop): Entity not found`.
Despite the wording, that means the **preset** is missing, not the track. So push
the sandbox first:

```bash
cd instruqt/sandbox
instruqt sandbox push
instruqt sandbox publish --message "initial"

cd ../track
uv run python ../../scripts/build_track.py
instruqt track validate
instruqt track push
```

`sandbox push` uploads a draft and `publish` makes it live. Neither one builds
anything. The setup script runs when a sandbox starts, so its output shows up in
`instruqt track logs` or in a `track test`.

## Things `track push` does to your files

- **It rewrites them.** It adds `id:` to the track, each challenge and each tab,
  adds `checksum`, reflows strings, and strips YAML comments. That's why
  rationale belongs in this README and in `sandbox/config.yml` (which `sandbox
  push` leaves alone), not in `track.yml`.
- **It re-adds keys you delete,** so deleting a key won't turn it off.

`build_track.py` carries the challenge and tab `id:` lines over from the pushed
copy, matching tabs by title, so rebuilding doesn't make the platform see new
challenges. After a push, re-read a file before you edit it.

## Testing a run

```bash
cd instruqt/track
instruqt track test temporal-agent-sandbox-workshop --keep-running
instruqt track logs temporal-agent-sandbox-workshop --since 30m
```

`track test` runs every challenge's setup, solve and check. `--keep-running`
leaves the sandbox up so you can get in. It **exits 0 even when it prints `FAIL`**,
so grep for `Track test succeeded`.

The checks use the local sandbox provider and the scripted model (see
`challenges/lib.sh`), so a green `track test` proves the Temporal code and the
lifecycle wiring. It doesn't prove that Daytona or the model work on the day. For
that, ask Max a question in the Max tab of a kept-running sandbox.

## Not proven yet

- **Cleanup.** `sandbox/scripts/cleanup-workstation` deletes the learner's Daytona
  sandboxes when a run ends. Presets scaffold only `setup-<vm>`, so whether
  Instruqt runs a preset's cleanup script hasn't been checked. If it doesn't, move
  the script to `track/track_scripts/cleanup-workstation`. Either way, after a
  session run `uv run python scripts/cleanup.py --all-learners`.
- **The VM image.** `instruqt/docker-28-3` is the image the platform workshop
  pushes with. A bare `ubuntu-2404-lts` fails `sandbox push` with
  `Failed to match any image formats: image not found`. Eventually, replace it with
  a custom image that has Ollama and the model pre-pulled.
