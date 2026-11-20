# RTK - Rust Token Killer

Run shell commands directly by default. Use RTK for supported commands with
verbose output when a summary is enough, for example `rtk git status`. If a
hook already wraps a command, run it directly.

For scripts, diffs, and debugging, run the native command to get exact
output. If a hook would rewrite it, use `rtk bypass <command>`.

If RTK prints a recovery path, open that file for the original output.
Otherwise, rerun a read-only command directly or with `rtk bypass` if a hook
would rewrite it.
