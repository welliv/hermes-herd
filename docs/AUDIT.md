# Vision vs. reality

Every claim in the README, checked against a test or a live run. Evidence lives
here so a claim without one can be deleted rather than believed.

Five suites, all run in CI:

- `python -m pytest tests -q` — **90 passed** (unit, two-device end-to-end, pairing, conflict resolution, knowledge scope, per-machine memory note).
- `python audit/matrix.py` — **55 checks**: crypto, merge orderings, env, items,
  forged stores, concurrency, surface, cost.
- `python audit/fuzz.py` — randomised three-device histories: edits, pushes,
  pulls, syncs and deletions in random order, then convergence, integrity and
  containment invariants.
- `python audit/fuzz_deep.py` — the harder version: three or four devices,
  deletions, secrets, and the rule that divergence is always explained by a
  recorded conflict.
- `python audit/fuzz_concurrent.py` — three `sync` processes racing.
- `python audit/fuzz_corrupt.py` — deleted, truncated, flipped and forged store
  objects between pulls.

Latest campaign: **100/100** three-device histories, **120/120** deep
three-or-four-device histories, **20/20** concurrent races, **24/24**
corrupt-store runs.

| Claim | Evidence |
|---|---|
| Pairing is one short code, and it works once | `test_the_code_is_twenty_characters_and_typed_once`, `test_a_used_code_does_not_pair_a_third_machine` |
| A wrong or expired code changes nothing | `test_a_wrong_code_says_so_and_changes_nothing`, `test_an_expired_code_is_refused` |
| "Take theirs" means the peer's value, not this machine's last push | `test_taking_theirs_after_this_machine_published_its_own_value` |
| A disagreement is settled, and then it is gone | `test_taking_the_store_value_settles_the_item`, `test_keeping_mine_publishes_it_and_the_other_machine_adopts` |
| The status line counts live disagreements | `test_summary_names_a_pending_conflict`, `test_joining_with_a_local_setting_takes_the_herd_value_quietly` |
| A second machine is useful in one command | `test_join_merges_without_breaking_the_new_machine`; matrix `merge/*` |
| Machine-bound keys never travel | `test_scrubbed_config_keeps_machine_keys_out_of_the_store`; fuzz asserts `webapp.port` never takes a peer value |
| A pull cannot delete the section the machine is running on | `test_remote_config_never_deletes_local_only_sections` |
| Secrets are encrypted in the store | `test_store_never_contains_plaintext`; matrix `crypto/no plaintext` |
| Machine env vars stay put | `test_secrets_are_synced_but_machine_vars_are_not`; matrix `env/skip list binds inbound` |
| A disagreement is never republished in a loop, and stays reported until both sides agree | `test_conflicts_disappear_once_the_sides_agree`; `fuzz_deep.py` asserts divergence ⇒ conflict |
| Conflicting edits are kept, and both sides are told | `test_same_key_edited_on_both_sides_keeps_local_and_records_it`; matrix `merge/both edited, both pushed, then pull`; audit C3 |
| A platform-specific skill is never installed elsewhere, and never deleted by that machine | `test_platform_specific_skill_is_not_installed_elsewhere`; matrix `items/platform *` |
| Deletions propagate | `test_deleting_a_skill_propagates`; matrix `items/skill deletion propagates` |
| Every pull is restorable | `test_pull_leaves_a_backup_that_undo_restores` |
| Only items this build knows can be written or deleted | matrix `attack/forged file id …`, `attack/unknown item id …` |
| A payload cannot be applied as a different item | matrix `attack/payload kind is bound to its item` |
| One corrupt item does not stop sync | matrix `attack/a missing object …`; audit C4 |
| Packs are byte-identical across machines | `test_dir_packing_is_deterministic` (gzip mtime pinned) |
| Status is read-only | `test_dry_run_status_does_not_write_objects` |
| Gateway bot tokens never travel | `test_gateway_tokens_stay_put` |
| Each agent tool is exercised | `test_tools.py` — status, diff, both directions, handlers that return rather than raise |
| Two devices cannot clobber each other's manifests | `test_git_transport_clones_to_a_second_machine`; matrix `concurrency/*` |
| Fast enough to run on session start | matrix `cost/*` — 200 skills 1.2 s, 5 MB skill 0.5 s, hook 2.3 ms |
| The plugin is loadable and honest about itself | `hermes plugins validate .` — all checks pass; declared tools, hooks and CLI match |
| The whole suite is green | `pytest` 64, `matrix.py` 55/55, randomised histories clean |

## What the vision promises that the build does not do yet

- **Nostr transport.** The store interface is transport-agnostic; only folder and
  git ship.
- **Sessions.** Not synced, by design. `state.db` is SQLite with a WAL.
- **Cron.** Off by default, opt-in with `--cron`.
- **Conflict resolution is manual.** Both sides keep their value and both record
  the disagreement; choosing one is still an edit. A resolver is the next UX
  piece, not a merge decision to guess.
- **Desktop surface.** Tools and CLI only.

## Deliberate non-goals

- Syncing the whole `~/.hermes` directory.
- A hosted service, an account, or telemetry.
- Auto-resolving a genuine conflict.
