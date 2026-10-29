# Agent instructions

@RTK.md

commit-message-default: auto

Push directly to `origin/main` by default. When asked to push, advance the
`main` JJ bookmark to the completed commits and push it. Do not create
feature bookmarks, branches, or pull requests unless the user explicitly
requests them.

Use small, independent JJ commits. Never transmit RF without explicit user
approval for the specific test. Normal operator use is `mise run start`
(transmit-enabled, background) and `mise run stop`; do not start the normal
station for agent verification. Default diagnostics to receive-only and use
`mise run start --receive-only` when a receive-only station is needed.
