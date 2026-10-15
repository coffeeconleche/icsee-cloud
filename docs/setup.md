# Setup and local prerequisites

1. Install Python 3.12+, FFmpeg, Android SDK platform-tools and build-tools, and a
   JDK. Create an Android emulator that can load ARM64 libraries. The validated
   route uses ARM translation in an Android emulator; ordinary x86-only system
   images can fail. Configure `ICSEE_AVD` when multiple AVDs exist.
2. Create `.venv` and install this project with `pip install -e ".[dev]"`.
3. Copy `.env.example` to `.env` and fill account credentials, camera selector,
   emulator name, and optional executable paths. Country selection is automatic
   unless overridden. `.env` is ignored.
4. Copy `examples/client.example.json` to `client.local.json` and fill your local
   client identity. The public release does not automate client identity extraction.
   Use your authorized developer identity or investigate your own verified app
   copy locally. Never post the completed file.
5. Supply locally verified `base.apk` and `split_config.arm64_v8a.apk` from the
   same iCSee version. APK authentication, version matching, and provenance must be
   established before the build. The build does not download or redistribute SDKs.

## Account country and server discovery

Normally leave `ICSEE_COUNTRY` empty and omit `ICSEE_REGION`. Like the app, the
client reuses a country saved from a successful login, or asks the vendor for its
automatic default on a fresh setup. It resolves the account API (`amsUrl`) and
native-helper service (`capsUrl`) before sending account credentials.

The ignored `account.local.json` stores a successful country under a hashed
account/client identifier. It contains no email, password, account token or camera
data. Accounts have separate entries; one account cannot inherit another's saved
country. A saved country takes precedence over the default when you travel.

The automatic default can describe your current location rather than an account
created elsewhere. On a fresh setup, use `ICSEE_COUNTRY=GB` (for example) to
override it with your account's two-letter country. After a successful login the
country is remembered, so the override can be cleared. This is independent of
the camera's location, recording timezone, and interface language. We have not
established an API that identifies every account's region from its email alone.

Explicit `ICSEE_REGION=sa` or `global` settings retain the fixed legacy backend
when country is empty. A nonempty country overrides it; `ICSEE_COUNTRY=auto` forces
automatic mode even with a legacy region present. With neither override
configured, automatic discovery is used.

The client does not sweep other regions on failure. Missing/ambiguous mappings
stop login. Discovered addresses must be HTTPS origins under `jftechws.com`, and
HTTP redirects are rejected. Discovery is reused per account within each cloud
client; reconnections create a new client and refresh it. A working local client
identity is required for discovery too. An unavailable cache does not prevent
login, but its country cannot be remembered until the cache is writable again.

## Build the Android helper

```powershell
.\.venv\Scripts\python.exe tools/build_android_helper.py `
  --input-dir path\to\verified-apks `
  --sdk path\to\Android\Sdk `
  --java-home path\to\jdk
```

The defaults target build-tools `36.0.0` and platform `android-37.0`; override
`--build-tools` and `--android-api` for an installed compatible toolchain. The
current build script supports Windows. It creates a locally signed helper APK,
its build record, and debug key under ignored `runtime/android-helper/`. The
viewer verifies the helper hash against that build record before installation.
Keep the generated private debug keystore between builds. For an existing helper,
use `--keystore path\to\its\local-debug.keystore` to preserve its signing identity;
Android rejects an update of the same package signed by a different key.

`ANDROID_SDK_ROOT`, `ANDROID_HOME`, and `JAVA_HOME` are supported. A ready helper
can be supplied with `ICSEE_HELPER_APK`; FFmpeg and ADB locations can be configured
with `ICSEE_FFMPEG` and `ICSEE_ADB`. The working copy uses `.env`, an ignored client
identity, and ignored binaries at runtime. It does not need the private research
scripts or the external REA checkout.

For an Android device already connected to ADB, no emulator start is required.
Exactly one ADB target should be selected; multiple connected devices currently
require configuring the ADB environment, such as `ANDROID_SERIAL`.
