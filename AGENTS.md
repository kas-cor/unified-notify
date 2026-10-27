# Unified Notify

Standalone Hermes plugin providing a shared SQLite notification queue, Telegram transport and authenticated owner replies to the originating profile's Bot Chat. It integrates through native Hermes plugin handlers, without modifying Hermes core or running another Telegram poller.

## Layout

- `plugin.yaml`: plugin metadata and user-facing settings; `__init__.py`: native Telegram handler registration and reply admission.
- `store.py`: queue and replies; `sender.py`: outbound transport; `dispatcher.py`: Bot Chat reply delivery.
- `cli.py`: enqueue, status, check, tick and setup entry point; `onboard.py`, `migrate_install.py`, `shared_prompt.py`: installation and shared instruction setup.
- `settings.py`: validation and internal defaults; `diagnostics.py`: Telegram status; `compat.py`, `entrypoints.py`, `legacy_*.py`: compatibility bridges.
- `skills/unified-notify-usage/SKILL.md`: shared agent instructions; `tests/test_*.py`: regression tests.

## Environment and checks

- The documented test environment is an installed Hermes environment with `python-telegram-bot` and both the Hermes source tree and this project on `PYTHONPATH`. There is no dependency manifest or lint configuration in this project.
- From the project root, the documented unittest command is `python -W error::ResourceWarning -m unittest discover -s tests -v`. Run tests on the owner's PC, not the infrastructure VPS. Unittest discovery does not run standalone pytest functions, including `tests/test_diagnostics.py`; that file additionally imports `pytest`.
- The documented plugin check is `hermes -p cron plugins doctor unified-notify --ci`. Doctor uses an empty isolated profile, so required Telegram IDs can cause registration failure even when the configured plugin works.
- `python3 /projects/unified-notify/cli.py setup` previews installation; `setup --apply` modifies configuration and files. `tick` performs external actions; do not run it as a harmless check.

## Invariants and pitfalls

- `HERMES_HOME` identifies the originating profile when enqueueing. Use a stable event `source_id`; duplicate keys are deduplicated. `queued`/`claimed` are not delivery; ambiguous or unknown outcomes must not be automatically resent.
- Only the single profile with the installed and enabled plugin runs transport. Replies must match the configured chat and owner, a post by the adapter's own bot, and a delivered notification receipt. Preserve fail-closed handling and no LLM fallthrough for admitted notification replies.
- The shared database is `~/.hermes/data/unified-notify.sqlite3`, outside the source tree. Preserve existing data and settings on updates; do not restore an old database backup over current data. Never commit secrets, local settings, receipts, logs or backups.
- `legacy_*.py` and compatibility launchers are wrappers, not replacements for the implementation modules. Do not copy a launcher over `store.py`, `sender.py` or `dispatcher.py`.
- Setup manages shared skill autoload and a single cron launcher; it does not restart Gateway or send test messages. Do not create a duplicate cron task. Changes to recipient or owner require a coordinated Gateway restart.
- Tests cover real `Application.process_update` without Telegram network access, but a manual function call does not verify scheduler guards. Consult `README.md` for deployment and live verification details.
