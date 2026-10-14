# Security and private data

Use this project only with accounts and cameras you are authorized to access.
Keep `.env`, `client.local.json`, real camera serials, recordings, logs, captures,
recovered APK material and private research outside Git tracking. The ignore rules
cover these locations; ignoring an already tracked file does not remove it from
history. Run `python tools/check_public_files.py` before staging source changes.

The public-file checker compares candidate sources against local account/identity
values without printing those values. It also flags tracked private/runtime paths.
It checks current files and tracking, not past commits. Before publishing a reused
repository, review its existing history separately.

The browser server and SDK forward are loopback only. Do not expose the viewer or
ADB directly to the internet; this local viewer has no remote-user authentication.
Cloud requests use certificate-verified TLS. SDK transport uses the vendor's own
connection implementation and its security properties are not fully audited here.

If reporting a bug, provide a sanitized error type, package version, and symptom.
Do not attach account responses, SDK requests, completed identity files, camera
footage, packet captures, or unreviewed diagnostic logs to a public issue.
