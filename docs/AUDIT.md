# Vision vs. reality

Every claim in the README, checked against a test or a live run. If a claim has no evidence, it does not belong in the README.

| Claim | Evidence |
|---|---|
| A second machine is useful in one command | `test_join_merges_without_breaking_the_new_machine`; live: `hermes sync join` on a second `HERMES_HOME` pulled 4 items and kept the host's Docker path |
| Machine-bound keys never travel | `test_scrubbed_config_keeps_machine_keys_out_of_the_store`, `test_join_merges_without_breaking_the_new_machine`, `test_remote_config_never_deletes_local_only_sections` |
| A pull cannot delete the section the machine is running on | `test_remote_config_never_deletes_local_only_sections` (regression for a real bug found in the live run) |
| Secrets are encrypted in the store | `test_store_never_contains_plaintext`; live: `grep -r sk-demo /store` returns nothing |
| Machine env vars stay put | `test_secrets_are_synced_but_machine_vars_are_not` |
| Conflicting edits are kept, not guessed | `test_same_key_edited_on_both_sides_keeps_local_and_records_it`, `test_two_edits_to_one_skill_keep_both`; live: `hermes sync conflicts` showed both values |
| Platform-specific skills are skipped | `test_platform_specific_skill_is_not_installed_elsewhere` |
| Deletions propagate | `test_deleting_a_skill_propagates` |
| Every pull is restorable | `test_pull_leaves_a_backup_that_undo_restores`; live: `hermes sync undo` restored `terminal`/`webapp` after a bad merge |
| Packs are byte-identical across machines | `test_dir_packing_is_deterministic` (gzip mtime pinned to zero) |
| Status is read-only | `test_dry_run_status_does_not_write_objects` |
| Gateway bot tokens never travel | `test_gateway_tokens_stay_put` — found live, when a first join pulled `TELEGRAM_BOT_TOKEN` |
| Each agent tool is exercised | `test_tools.py` — status, diff, both sync directions, and three handlers that must return rather than raise |
| Two devices cannot clobber each other's manifests | `test_git_transport_clones_to_a_second_machine`; per-device manifest files by construction |
| Fast enough to run on session start | live: 76 items / 1.2 MB packed — scan 0.50 s, push 0.60 s, status 0.60 s on this machine's real skills (57 MB on disk) |
| The plugin is loadable and honest about itself | `hermes plugins validate .` — all checks pass, security scan **safe**, declared tools and hooks match registrations |
| The whole suite is green | `python -m pytest tests -q` → **48 passed** |

## What the vision promises that the build does not do yet

- **Nostr transport.** The store interface is transport-agnostic; only folder and git ship. Nostr needs chunking for relay message limits and NIP-42 auth handling before it is more than a demo.
- **Sessions.** Not synced, by design. `state.db` is SQLite with a WAL; file-syncing it corrupts history. A future version could export sessions as append-only records instead of syncing the database.
- **Cron.** Off by default, opt-in with `--cron`. A job on three machines runs three times.
- **Interactive conflict resolution.** `hermes sync conflicts` shows both sides and where the losing skill was saved; choosing a side is still a manual file edit.
- **Desktop surface.** Tools and CLI only. A status pane in Hermes Desktop would make drift visible without typing anything.

## Deliberate non-goals

- Syncing the whole `~/.hermes` directory.
- A hosted service, an account, or telemetry.
- Auto-resolving a genuine conflict. Guessing at intent is worse than showing two values.
