"""Config py2app pentru a construi Serato Migrator.app.

Rulare: python3 setup.py py2app
"""
from setuptools import setup

APP = ["main.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "iconfile": "AppIcon.icns",
    "plist": {
        "CFBundleName": "Serato Migrator",
        "CFBundleDisplayName": "Serato Migrator",
        "CFBundleIdentifier": "com.gabrielcolceriu.seratomigrator",
        "CFBundleShortVersionString": "0.1.0",
        "NSHumanReadableCopyright": "© Gabriel Colceriu",
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
