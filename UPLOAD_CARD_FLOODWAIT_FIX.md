# Upload Card Cleanup + FloodWait Fix

## Upload card bug

The visible upload task remained in `UPLOADING 100%` after the user-facing
Telegram upload completed because the same coroutine then uploaded the file a
second time to the configured log channel. The progress callback correctly
ignored log-channel progress, but task removal happened only after that slow
copy finished.

### Fix

- User upload slot is released immediately after delivery.
- The visible upload task/card is marked complete and removed immediately.
- Log-channel copying runs as an invisible background upload.
- Background log copies still use the global two-upload limiter.
- Temporary media/thumbnail cleanup is owned by the background task, so files
  are not deleted before logging finishes.
- Interactive priority is released after user delivery; log copying no longer
  blocks the profile/channel bulk queue.

This is applied to both the main quality-button flow and the shared
xHamster/Eporner advanced pipeline.

## FloodWait warning

A `FloodWait: 34s` is Telegram's edit rate limit, not a Koyeb crash. Previously
`force=True` stage updates could bypass the timestamp pause after FloodWait and
attempt another edit early.

### Fix

- Dedicated per-user hard FloodWait deadline.
- Even forced/stage-changing updates respect that deadline.
- Normal live dashboard edits are coalesced to a 5-second interval.
- Once Telegram accepts an edit, the expired hard cooldown is cleared.

## Verification

- 16 unit tests pass.
- Explicit 34-second FloodWait simulation confirms two forced refreshes cause
  only one Telegram edit attempt.
- Background-log simulation confirms the media function returns, dashboard card
  clears and interactive priority drops to zero while log upload is still
  running.
- All Python compile/import checks pass.
