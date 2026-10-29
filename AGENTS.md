# Agent instructions

@RTK.md

commit-message-default: auto

Use small, independent JJ commits. Never transmit RF without explicit user
approval for the specific test. Normal operator use is `mise run start`
(transmit-enabled, background) and `mise run stop`; do not start the normal
station for agent verification. Default diagnostics to receive-only and use
`mise run start -- --receive-only` when a receive-only station is needed.
