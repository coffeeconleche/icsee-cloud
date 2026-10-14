"""Build a private debug probe from local user-supplied vendor APKs; no dependencies are downloaded."""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile

import argparse, os, shutil
parser = argparse.ArgumentParser(description='Build the local helper from user-supplied, verified SDK APKs')
parser.add_argument('--input-dir', type=Path, required=True, help='Directory containing base.apk and split_config.arm64_v8a.apk')
parser.add_argument('--sdk', type=Path, default=Path(os.environ.get('ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or Path.home()/'AppData/Local/Android/Sdk'))
parser.add_argument('--java-home', type=Path, default=Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else None)
parser.add_argument('--build-tools', default='36.0.0')
parser.add_argument('--android-api', default='android-37.0')
parser.add_argument('--output', type=Path, default=Path('runtime/android-helper'))
parser.add_argument('--keystore', type=Path, help='Reuse the local debug signing key of an existing installed helper')
args = parser.parse_args()
ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / 'android/helper'
SDK = args.sdk.resolve()
TOOLS = SDK / 'build-tools' / args.build_tools
JAVA = args.java_home/'bin' if args.java_home else Path(shutil.which('java') or '').parent
if not JAVA.is_dir() or not (JAVA/'javac.exe').exists():
    parser.error('Provide --java-home pointing to a Windows JDK with javac')
ANDROID = SDK / 'platforms' / args.android_api / 'android.jar'
OFFICIAL = args.input_dir.resolve()
OUTPUT = args.output.resolve()
BUILD = OUTPUT / 'build'
BUILD.mkdir(parents=True, exist_ok=True)
(BUILD / "classes").mkdir(exist_ok=True)
(BUILD / "dex").mkdir(exist_ok=True)

def run(args):
    result = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    with (BUILD / "build.log").open("a", encoding="utf-8") as out:
        out.write("\n" + str(args[0]) + "\n" + result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Build step failed: {Path(str(args[0])).name}; inspect build/build.log")

(BUILD / "build.log").write_text("",encoding="utf-8")
run([JAVA / "javac.exe", "-source", "8", "-target", "8", "-classpath", ANDROID, "-d", BUILD / "classes", *HERE.glob("src/**/*.java")])
classes = list((BUILD / "classes").rglob("*.class"))
run([JAVA / "java.exe", "-cp", TOOLS / "lib/d8.jar", "com.android.tools.r8.D8", "--min-api", "26", "--lib", ANDROID, "--output", BUILD / "dex", *classes])
seed = BUILD / "seed.apk"
run([TOOLS / "aapt2.exe", "link", "-I", ANDROID, "--manifest", HERE / "AndroidManifest.xml", "-o", seed])
unsigned = BUILD / "unsigned.apk"
official_dex = []
with zipfile.ZipFile(unsigned,"w",compression=zipfile.ZIP_DEFLATED) as target:
    with zipfile.ZipFile(seed) as archive:
        for name in archive.namelist():
            if name != "resources.arsc": target.writestr(name,archive.read(name))
    with zipfile.ZipFile(OFFICIAL / "base.apk") as archive:
        for name in archive.namelist():
            if name.startswith(("assets/","res/")) or name == "resources.arsc" or (name.startswith("classes") and name.endswith(".dex")):
                target.writestr(name,archive.read(name))
                if name.startswith("classes") and name.endswith(".dex"): official_dex.append(name)
    next_index = max([1 if name == "classes.dex" else int(name[7:-4]) for name in official_dex])+1
    target.write(BUILD / "dex/classes.dex",f"classes{next_index}.dex")
    with zipfile.ZipFile(OFFICIAL / "split_config.arm64_v8a.apk") as archive:
        for name in archive.namelist():
            if name.startswith("lib/arm64-v8a/") and name.endswith(".so"): target.writestr(name,archive.read(name))
aligned = BUILD / "aligned.apk"
run([TOOLS / "zipalign.exe","-f","4",unsigned,aligned])
key = args.keystore.resolve() if args.keystore else BUILD / "local-debug.keystore"
if not key.exists():
    run([JAVA / "keytool.exe","-genkeypair","-keystore",key,"-storepass","android","-keypass","android","-alias","localdebug","-dname","CN=Local Analysis Only","-keyalg","RSA","-keysize","2048","-validity","3650"])
apk = OUTPUT / "local-icsee-probe.apk"
run([JAVA / "java.exe","-jar",TOOLS / "lib/apksigner.jar","sign","--ks",key,"--ks-pass","pass:android","--ks-key-alias","localdebug","--out",apk,aligned])
run([JAVA / "java.exe","-jar",TOOLS / "lib/apksigner.jar","verify","--verbose",apk])
digest = hashlib.sha256(apk.read_bytes()).hexdigest()
(OUTPUT / "build-result.json").write_text(json.dumps({"apk":str(apk),"sha256":digest,"bytes":apk.stat().st_size,"original_dex":official_dex,"instrumentation":"local.icsee.probe/.ProbeInstrumentation","installed":False},indent=2),encoding="utf-8")
print(json.dumps({"status":"built-and-signature-verified","apk":str(apk),"bytes":apk.stat().st_size}))
