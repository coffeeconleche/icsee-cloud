# Third-party components

The project uses Python dependencies declared in `pyproject.toml`: cryptography,
Pillow, PyAV and tzdata. Each retains its own license. PyAV relies on FFmpeg
libraries; an installed FFmpeg executable and its particular build license are
separate runtime prerequisites.

Android SDK/JDK tools, the verified iCSee APK and native vendor SDK libraries are
user-supplied build/runtime inputs. They are not licensed by this project's LICENSE
and are not included in its public source or Python package. Building a local
helper does not grant rights to redistribute vendor APKs or SDK binaries.

REA is an external research tool used during investigation. Its checkout is kept
outside this repository and is not needed to run the Python package. No REA code
has been copied into this package.
