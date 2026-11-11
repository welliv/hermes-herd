# Vision vs. reality

Every claim in the README, checked against a test or a live run. Evidence lives
here so a claim without one can be deleted rather than believed.

Five suites, all run in CI:

- `python -m pytest tests -q` — **172 passed** (unit, two-device end-to-end, pairing, conflict resolution, knowledge scope, per-machine memory note, approval, undo, and the 1.2.1 review tests in `test_review_1_2_1.py` and `test_endpoint_pin.py`).
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
| API keys are not read or written | `test_sync_never_opens_dotenv`; `test_secrets_are_not_synced_even_when_asked`; matrix `env/asking to sync keys does not read or write .env` |
| Credential-named keys in `config.yaml` never reach the store (any depth, lists, camelCase, `mcp_servers.*.env` / `headers`) | `test_model_api_key_never_reaches_the_store`; `test_case_variants_nested_lists_and_other_env_sections_stay_local`; `test_credential_names` / `test_not_credential_names`; `test_three_homes_through_a_bare_repo_leak_no_secret` |
| `shared:` cannot lift the credential rule | `test_shared_cannot_lift_the_credential_rule` |
| A peer cannot inject, overwrite or delete a local credential (null, empty list, shape change, `--take theirs`) | `test_a_peer_cannot_inject_or_overwrite_credentials`; `test_incoming_poison_cannot_overwrite_or_delete_local_secrets`; `test_a_real_push_cannot_null_out_a_local_secret`; `test_fresh_join_does_not_receive_a_poisoned_api_key`; `test_take_theirs_does_not_import_or_drop_credentials`; `test_list_change_from_a_peer_keeps_local_list_credentials`; `test_shape_changes_do_not_drop_local_credentials` |
| A peer cannot point a local credential elsewhere (`base_url`, `provider`, MCP `command` / `args`, …); the held change is shown and `--take theirs` applies it | `test_peer_cannot_redirect_local_key_via_base_url`; `test_peer_cannot_hand_local_mcp_env_to_a_new_command`; `test_peer_cannot_add_an_endpoint_or_switch_provider_beside_a_key`; `test_held_endpoint_is_shown_does_not_ping_pong_and_take_theirs_applies_it`; `test_held_list_endpoint_is_shown_and_take_theirs_applies_it`; `test_a_header_credential_pins_its_endpoint` |
| Endpoints with no local credential beside them still sync, and ordinary edits raise no conflict | `test_endpoint_without_local_credential_still_syncs`; `test_endpoints_follow_onto_a_machine_without_the_key`; `test_normal_edits_beside_a_key_raise_no_conflict` |
| Cron jobs land only where this machine opted in, and are never deleted elsewhere | `test_cron_is_not_installed_where_cron_sync_is_off`; `test_cron_deletion_does_not_touch_a_declining_machine`; `test_cron_still_syncs_where_both_machines_opted_in`; `test_cron_skip_is_recorded_and_not_reapplied_until_opt_in` |
| `--cron` works at `init`, `join`, `pair` and `pair --code` | `test_pair_without_cron_does_not_install_jobs`; `test_pair_cron_on_the_first_machine_opts_it_in`; `test_pair_cron_on_a_machine_that_already_syncs_turns_it_on`; `test_cli_pair_passes_cron_to_the_first_machine` |
| git, ssh and credential helpers get a minimal environment, never provider keys | `test_git_env_drops_provider_keys`; `test_git_env_keeps_platform_runtime_and_drops_everything_else`; `test_git_children_do_not_see_provider_keys`; `test_ssh_and_credential_helper_see_only_the_git_environment`; `test_every_package_subprocess_passes_the_git_environment` |
| A newer local file is not replaced by an older store copy | `test_sync_keeps_a_newer_local_soul` |
| Undo deletes files the pull created | `test_undo_removes_a_skill_the_pull_created` |
| A remote-only change is a pull | `test_a_remote_change_is_a_pull_not_a_push` |
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
| The whole suite is green | `pytest` 172, `matrix.py` 55/55, randomised histories clean |

## What the vision promises that the build does not do yet

- **Nostr transport.** The store interface is transport-agnostic; only folder and
  git ship.
- **Sessions.** Not synced, by design. `state.db` is SQLite with a WAL.
- **Cron.** Off by default, opt-in per machine with `--cron`.
- **Conflict resolution is manual.** Both sides keep their value and both record
  the disagreement; choosing one is still an edit. A resolver is the next UX
  piece, not a merge decision to guess.
- **Desktop surface.** Tools and CLI only.

## Deliberate non-goals

- Syncing the whole `~/.hermes` directory.
- A hosted service, an account, or telemetry.
- Auto-resolving a genuine conflict.
