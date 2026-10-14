# Architecture

The public code separates three layers:

1. `protocol.py` reproduces native request signing, key derivation, login encoding,
   and block padding. `cloud.py` performs TLS requests, sign-in, device listing,
   and selection without saving response bodies or printing account tokens.
2. `android/helper` calls the vendor SDK through reflection, obtaining the device
   authorization associated with the account and establishing the native remote
   camera connection. `viewer.py` starts the helper, creates a loopback ADB forward,
   and supervises the decoder. No screen capture is involved.
3. `media.py` receives framed HEVC and G.711 A-law packets, validates their headers,
   and produces a timestamped NUT stream. `recorder.py` copies video and encodes
   audio to AAC while FFmpeg makes segmented MKV recordings and a browser preview.

The helper binds only to Android loopback. The viewer binds only to PC loopback.
SDK account initialization uses a transient request file in the app's private
directory; it is deleted after reading. Long-lived credentials remain in process
memory and the ignored local configuration file.

SDK requests and cloud calls are credentialed connections to the vendor's service.
Vendor binaries, developer identities, user credentials and captures are not part
of the distributable source. The UI is intentionally independent of recording:
closing a page does not stop a scheduled job.

Linux/ARM container hosting is a future backend candidate. Windows Task Scheduler
and the current helper build tool are the validated orchestration environment.
