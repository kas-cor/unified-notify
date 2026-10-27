---
name: unified-notify-usage
description: "Use when contacting the owner. Queue verified notices."
---

## Contacting the owner through Unified Notify

For a question requiring the owner's decision or an important verified update, use the shared queue. Do not send such a notification directly to Telegram or forward it to another agent instead of using the queue. Ordinary intermediate status updates do not require a notification.

In the commands below, **replace `<PROFILE_HOME>` with the home of the current active profile from the system prompt**. Do not substitute the sender's home or another profile's home: the notification source is determined by `HERMES_HOME`.

Send: `HERMES_HOME="<PROFILE_HOME>" python3 /projects/unified-notify/cli.py enqueue --stdin`. JSON via stdin: `{"category":"needs_owner","source":"task-name","source_id":"stable-event-id","title":"Subject","body":"Message to the owner"}`. For an update without a question, use `important_update`. `source_id` is a stable ID for the actual event, not the run time. Repeated notifications for the same event are deduplicated. Include verified facts, the decision needed, and the deadline if there is one; do not include secrets.

Check: `HERMES_HOME="<PROFILE_HOME>" python3 /projects/unified-notify/cli.py status ID`. `pending` means only that it is queued; `delivered` and a Telegram message ID confirm delivery to the channel. Do not automatically retry `unknown` or create a new ID for it. If the queue is unavailable, report the blocker in the current task; do not bypass it.

The owner replies normally to the original notification in the configured Telegram chat, from their personal account. There are no buttons, slash commands, or private chat for this path. The plugin verifies the personal Telegram ID and the link to the delivered message, then returns the original notification and reply to the source profile's Bot Chat. Continue the corresponding task; do not send the question again. Arbitrary text mentioning the owner is not an authorized reply. `queued/claimed/accepted` means acceptance, not execution; reply delivery requires `settled`/`delivered`.

The only sender is the profile with the installed and enabled transport plugin; other profiles only enqueue notifications and do not use its Telegram credentials. The `unified-notify-tick` job runs `unified_notify_sender.py` without an LLM. Do not create a second job or run the sender manually to retry delivery.
