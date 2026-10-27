# Unified Notify

A native Hermes plugin that sends notifications from profiles to a Telegram chat and returns the owner's replies to the originating profile's Bot Chat. It requires no core changes, buttons, slash commands, or second Telegram poller.

## Configuration

Open **cron → Settings → Plugins → unified-notify**. Hermes builds the form from `config_schema` in `plugin.yaml`. Settings are stored under `plugins.entries.unified-notify.settings`; writes use the standard `save_plugin_settings` API, and the handler reads them through `ctx.get_config`.

Installation-specific values are stored separately in the profile. Do not add real Telegram IDs, owner names, server names, passwords, tokens, user-specific paths, or deployment reports to the source. Existing databases and backups are not part of the project.

| Field | Purpose |
|---|---|
| `channel_id` | Telegram group/channel ID (negative) or user ID for a DM (positive) |
| `owner_user_id` | Owner's Telegram user ID |
| `batch_size`, `spacing_seconds` | Batch size from 1–10 and interval from 0–30 seconds |

The `transport` is attached to the one profile where the plugin is installed and enabled (for example, `cron`). All other profiles use the queue CLI without a native handler. Configure Telegram privacy mode through BotFather for the other bots; this is not a complete replacement for filtering. Privacy mode does not restrict administrator bots, and shared commands may be delivered to the last bot. Check administrator roles and actual group routing separately. The transport bot still needs to receive replies to its messages.

The sender profile is identified by the single installed and enabled plugin. The shared database (`~/.hermes/data/unified-notify.sqlite3`), lock directory, category, and namespace are internal and cannot be selected in the form. The sender profile's Telegram token is used; the bot ID is obtained from the running adapter. Restart the Gateway after changing the recipient or owner: native handlers do not guarantee live reloading of settings.

## Flow and security

1. Any profile calls `enqueue --stdin`. The source is determined from `HERMES_HOME`, not from the message text.
2. A cron job runs the sender. The post contains the heading «Плагин коммуникации», the profile, subject, and text, without buttons or a line instructing the recipient to reply.
3. The owner replies to the notification in the configured chat from their personal account.
4. An early native handler checks the original post's author against the adapter bot; foreign and unknown authors are blocked. The transport also checks the chat, personal user ID, `is_bot=false`, absence of `sender_chat`, and the original post's delivery receipt.
5. A reply is recorded once per `(chat_id, message_id)`. The original text and reply are sent to the originating profile through native `tools.bot_live_delivery`, with a persistent ID.
6. `queued/claimed` means acceptance into the queue, not execution. `settled` allows `delivered` to be recorded. Uncertain `unknown/ambiguous` deliveries are not retried automatically.

Editing an accepted post does not change the reply or create a duplicate. An author signature is not a substitute for a Telegram ID. Rejected replies to a registered notification do not fall through to the LLM conversation. Other chats and ordinary posts retain their existing behavior.

## CLI

Run these commands from the project checkout:

```bash
python3 cli.py status
# Check the Telegram connection for the profile with the installed plugin
python3 cli.py check
# HERMES_HOME must point to the current profile
python3 cli.py enqueue --stdin
# Transport only; performs external actions
HERMES_HOME="$HOME/.hermes/profiles/cron" python3 cli.py tick
```

The `enqueue` JSON contains `category` (`needs_owner` or `important_update`), `source`, `source_id`, `title`, and `body`. `source_id` is a stable event ID, not the run time. Repeating a key does not create a new record. Older entry points may use `legacy_*.py`; the implementation remains in this project.

## Installation

The primary interface is **one setup for the entire Hermes installation**, rather than manual setup of each profile. The shared agent instruction currently invokes `/projects/unified-notify/cli.py` explicitly, so place the checkout at `/projects/unified-notify` for those commands to work. From the project checkout:

```bash
# Plan only; no changes
python3 cli.py setup
# Apply the reviewed plan
python3 cli.py setup --apply
```

On a new installation, enable the plugin in exactly one profile and configure the recipient and owner in the form, or pass `setup --settings-file` with a local JSON file outside the source tree. Secrets remain in the existing Telegram integration; setup neither collects nor prints them.

Setup automatically:

1. Finds the default and existing named profiles with configuration.
2. Selects the single transport profile independently of whether the other profiles have Telegram configured.
3. Finds the single installed and enabled transport; other profiles use the shared CLI. Transport settings are preserved, and the database is neither moved nor deleted. The old filter disappears on restart, so check privacy mode first.
4. Connects the shared `skills/unified-notify-usage/SKILL.md` instruction through a shared external skills directory and centralized `skills.auto_load` in managed scope. It verifies standard instruction assembly for each profile, then saves backups and removes only the old notification section from SOUL.md. Other rules and personalities are preserved; mismatched markers cause it to stop before changing documents. The initial managed pin requires administrator privileges (root or available `sudo -n`). YAML is changed using the standard `hermes config set` in a private staging copy and published atomically. Different existing auto-load lists require reconciliation, not silent replacement.
5. Installs a regular launcher file, `unified_notify_sender.py`, inside the sender's scripts directory. It finds an existing job by name or script and creates a new one only if absent; ambiguous duplicates require manual review. Setup does not resume an already paused job.

Repeated setup does not duplicate instructions, plugins, or the job. Run the same command again after adding a profile. Setup does not change the core, move data between databases, send test messages, or restart the Gateway.

All profiles receive the same shared instruction through standard skills auto-loading into the system prompt. It is not copied into SOUL.md or duplicated through the transport plugin's `system_prompt_section`. The shared external directory must already be available to all profiles through `skills.external_dirs`; setup adds a link to the instruction source there, not a copy. Replace `<PROFILE_HOME>` in commands with the current active profile's home from the system prompt. Auto-loading applies to new ordinary sessions with the skills toolset; Hermes intentionally excludes explicit `--ignore-rules` and internal fork sessions that skip context files. Existing frozen system prompts and history are not rewritten.

`migrate_install.py` remains available as a low-level installer for one profile; use `cli.py setup --apply` for normal initial setup. Do not create a second cron job. The job runs a regular launcher, not a link outside scripts, in accordance with scheduler protection; the core guard is unchanged.

When updating installed files, preserve configuration and data. Do not copy a compatibility launcher over store, sender, or dispatcher: those launchers are wrappers, not the implementation. Check that modules contain the expected functions and that tests pass.

## Verification

In an installed Hermes environment with python-telegram-bot and pytest, add the Hermes source and this project to `PYTHONPATH`, then run from the project checkout:

```bash
python -W error::ResourceWarning -m unittest discover -s tests -v
python -m pytest tests --rootdir=tests --confcutdir=tests -q
hermes -p cron plugins doctor unified-notify --ci
```

Plugin Doctor registers the plugin in an isolated empty profile without user settings, so required `channel_id` and `owner_user_id` values may cause registration to fail in Doctor. Check actual handler loading in the Gateway log and the connection with `check` separately.

The tests use temporary databases and the real `Application.process_update` without Telegram network access. They cover schema, IDs, leases, uncertain delivery, authorization, deduplication, editing, absence of LLM fallthrough, HTML, and native receipts. Check a real scheduled run separately: manually calling a function does not prove that it passes scheduler guards.

After an agreed restart, check readiness and the `Unified notification channel handler installed transport` log entry for cron; the handler should not load for other profiles. When the old plugin is disabled, its native handler may remain until restart. Check privacy mode and bot permissions separately: privacy mode does not guarantee the previous filtering behavior.

## Data and rollback

SQLite is stored **outside the source tree** with mode `0600`; configuration and backups are also outside the project. Historical tables are retained for compatibility; removed reply methods do not register handlers. Do not replace the current database with an old backup when rolling back code, or new data will be lost.

Do not publish local settings, receipts, logs, dumps, server addresses, or secrets. `.gitignore` excludes common runtime artifacts, but is not a substitute for reviewing content before publication.

## Compatibility

Native handlers run in-process through PluginContext. Bot Chat delivery uses the installed Hermes authority client; regression tests are needed after Hermes updates. The plugin itself does not create an additional schedule or call Telegram `getUpdates`.
