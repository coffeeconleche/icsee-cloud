# Setup and local prerequisites

1. Install Python 3.12+, FFmpeg, Android SDK platform-tools and build-tools, and a
   JDK. Create an Android emulator that can load ARM64 libraries. The validated
   route uses ARM translation in an Android emulator; ordinary x86-only system
   images can fail. Configure `ICSEE_AVD` when multiple AVDs exist.
2. Create `.venv` and install this project with `pip install -e ".[dev]"`.
3. Copy `.env.example` to `.env` and fill account credentials, camera selector,
   region, emulator name, and optional executable paths. `.env` is ignored.
4. Copy `examples/client.example.json` to `client.local.json` and fill your local
   client identity. The public release does not automate client identity extraction
   or region discovery. Use your authorized developer identity or investigate your
   own verified app copy locally. Never post the completed file.
5. Supply locally verified `base.apk` and `split_config.arm64_v8a.apk` from the
   same iCSee version. APK authentication, version matching, and provenance must be
   established before the build. The build does not download or redistribute SDKs.

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
