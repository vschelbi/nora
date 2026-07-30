from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from setuptools.command.install import install
from setuptools.command.develop import develop
import subprocess
import os
import sys
import re

TRANSLATION_SERVER_REPO = "https://github.com/zotero/translation-server.git"
TRANSLATION_SERVER_DIR = os.path.join("src", "nora", "translation_server")
TRANSLATION_SERVER_GIT = os.path.join(TRANSLATION_SERVER_DIR, ".git")

# The translation server is pinned to a known-good commit. Cloning its
# HEAD instead would make every install pick up whatever dependencies
# were last bumped upstream: translation-server moved to jsdom 29 in
# April 2026, which needs the require(esm) support added in Node 20.19
# and breaks any earlier Node 20 with a cryptic ERR_REQUIRE_ESM.
# Bump this once you are on Node >= 20.19
TRANSLATION_SERVER_REF = "5087368"


# ───────────────────────────────────────────────
# 🧩 1. Node.js version check
# ───────────────────────────────────────────────
def check_node_version(min_major: int = 18, max_major: int = 20):
    """Check that Node.js is installed and at least the required major version.
    """
    try:
        result = subprocess.run(
            ["node", "-v"],
            capture_output=True,
            text=True,
            check=True
        )
        version = result.stdout.strip().lstrip("v")
        major = int(re.match(r"(\d+)", version).group(1))

        if major < min_major:
            sys.exit(
                f"❌ Node.js >= {min_major} is required, but found v{version}.\n"
                f"👉 Please install Node.js >={min_major} and <={max_major}."
            )
        if major > max_major:
            sys.exit(
                f"❌ Node.js <= {max_major} is required, but found v{version}.\n"
                f"👉 Please install Node.js >={min_major} and <={max_major}."
            )
        print(f"✅ Node.js version {version} OK")
        sys.stdout.flush()

    except FileNotFoundError:
        sys.exit(
            f"❌ Node.js is not installed or not on PATH.\n"
            f"👉 Please install Node.js >={min_major} and <={max_major} before "
            f"installing NoRA."
        )


# ───────────────────────────────────────────────
# 📦 2. Translation server preparation
# ───────────────────────────────────────────────
def checkout_translation_server_ref():
    """Move the translation_server clone to the pinned commit, unless it
    is already there.
    """
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=TRANSLATION_SERVER_DIR,
        capture_output=True,
        text=True,
    )
    if head.returncode == 0 and head.stdout.strip().startswith(TRANSLATION_SERVER_REF):
        return

    print(f"📌 Checking out translation_server at {TRANSLATION_SERVER_REF}...")
    sys.stdout.flush()
    subprocess.run(
        ["git", "fetch", "--tags", "origin"],
        cwd=TRANSLATION_SERVER_DIR,
        check=False,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    subprocess.run(
        ["git", "checkout", TRANSLATION_SERVER_REF],
        cwd=TRANSLATION_SERVER_DIR,
        check=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    # The translators live in nested submodules, whose commits differ
    # from one translation-server revision to the next
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=TRANSLATION_SERVER_DIR,
        check=True,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def prepare_translation_server():
    """Clone translation_server and run npm install if needed."""
    check_node_version()

    # Clone submodule if missing
    if not os.path.exists(TRANSLATION_SERVER_DIR) or not os.path.exists(TRANSLATION_SERVER_GIT):
        print(f"📦 Cloning translation_server from {TRANSLATION_SERVER_REPO}...")
        sys.stdout.flush()
        subprocess.run(
            ["git", "clone", "--recurse-submodules", TRANSLATION_SERVER_REPO, TRANSLATION_SERVER_DIR],
            check=True,
            text=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    # Make sure we build against the pinned revision
    checkout_translation_server_ref()

    # Run npm install if package.json present
    package_json = os.path.join(TRANSLATION_SERVER_DIR, "package.json")
    if os.path.exists(package_json):
        print("📦 Installing npm dependencies for translation_server...")
        sys.stdout.flush()
        subprocess.run(
            ["npm", "install"],
            cwd=TRANSLATION_SERVER_DIR,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )


# ───────────────────────────────────────────────
# ⚙️ 3. Custom setuptools commands
# ───────────────────────────────────────────────
class CustomBuildPy(build_py):
    def run(self):
        prepare_translation_server()
        super().run()


class CustomInstall(install):
    def run(self):
        prepare_translation_server()
        super().run()


class CustomDevelop(develop):
    def run(self):
        prepare_translation_server()
        super().run()


# ───────────────────────────────────────────────
# 🧠 4. Setup configuration
# ───────────────────────────────────────────────
setup(
    name="nora",
    version="3.3",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    cmdclass={
        "build_py": CustomBuildPy,
        "install": CustomInstall,
        "develop": CustomDevelop,
    },
)
