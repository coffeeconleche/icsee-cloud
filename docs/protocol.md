# Reverse-engineering findings

These notes summarize observations from a verified iCSee `7.9.4_G` app and one
authorized account/camera. They are not a compatibility promise for other versions.

## Account API

The app URL-encodes the account username before calling the SDK. The encrypted
login body is `account=<encoded username>&pass=<native encoded password>`.
Password encoding preserves the native punctuation set and uses `%20` for spaces.

Requests use `/METHOD/v3/NONCE/SIGNATURE.rs`. The nonce contains a seven-digit
counter and millisecond timestamp. The signature combines the client UUID, key,
secret and nonce through the observed byte permutation and MD5 digest. The AES
key is derived from the latter half of the nonce plus the client secret. Bodies
use AES-128 ECB with PKCS padding and uppercase hexadecimal text. Responses can
be plain JSON or encrypted hexadecimal JSON after URL decoding.

`loginExist` yields an account token; `msdlistCode` lists owned/shared devices.
The tested account belongs to the South America MI/CAPS region. Valid credentials
sent to another region can look like a nonexistent account. A client identity is
not the account login and must be supplied privately.

The app's country lookup uses `/phoneAndUrlByCountry/va1/TIMESTAMP/SIGNATURE.rs`
on `https://ams.jftechws.com`, with the same client identity/signature derivation
and a millisecond timestamp without the account API's counter prefix. The body
is ordinary form data: `isoCode=<two-letter country>&urlVersion=`. It does not
include account credentials or an account token. Responses use the same
JSON/encrypted-hex decoding as account calls.

The returned `data.regionUrl` contains country-specific `countryNo`, `amsUrl`,
and `capsUrl` fields. `data.defaultCountry` can point to a different country,
reflecting the requesting computer's location. Select the explicit country
entry; do not substitute the default when the account belongs elsewhere.
The client implements this lookup when `ICSEE_COUNTRY` is set, without an
automatic sweep of other regions. Native SDK fallback behavior is not fully traced.

## Camera transport

The tested camera uses RPS and account-derived device authorization. Its stream
is delivered by the native SDK, not a public RTSP URL returned by the login API.
The transport includes native proprietary connection logic; this project has not
replaced it with a pure Python network implementation.

The helper obtains video callbacks separately from audio and metadata. Verified
Sofia headers: video keyframes `00 00 01 FC` (16-byte header), other video frames
`00 00 01 FD` (8-byte header), and audio `00 00 01 FA` with codec `0E` and rate `02`
(G.711 A-law, mono 8 kHz). Declared payload sizes are validated before use.

With audio enabled, the helper sends a 20-byte `ICAV` envelope in network byte
order: magic, one-byte type, three reserved bytes, payload length, and monotonic
arrival milliseconds, followed by the original SDK packet. The observed video
cadence has two 320-sample audio packets per video frame; the audio sample clock
avoids drift from the rounded video FPS field. Other audio formats currently fail
explicitly and need their own tested decoder/header handling.

Static analysis used an external REA checkout with JADX plus local native ELF
inspection. Captures, raw account responses, recovered identities and device
identifiers remain private. No vendor client secrets are published as examples.
