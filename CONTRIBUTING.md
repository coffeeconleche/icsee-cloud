# Contributing

Install the development extras and run `python -m pytest`. Tests should be offline
and use synthetic credentials and packet fixtures. Live account/camera testing is
opt-in and must never run from CI or write personal data to public test fixtures.

Keep account/cloud APIs, native helper transport, media framing and job scheduling
separate. Describe the firmware/app versions actually tested. Add a protocol or
reconnection regression test when a change alters signing, framing, timing or stop
behavior. Include sanitized validation results with proposed changes.

Run `python tools/check_public_files.py` before preparing a commit. Native SDKs,
APKs and local research tools are external prerequisites, not source dependencies
to copy into a contribution. Add new controls through the package APIs instead of
hard-coding a camera name, serial, account, path or shared developer identity.
