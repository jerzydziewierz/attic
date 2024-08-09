import setuptools
import subprocess

VERSION_BASE = "0.0.0"


def get_version():
    """

    try using `git rev-parse HEAD --short` here to get the git commit.
    then append that to the version string.
    """
    try:
        command = "git rev-parse --verify --short=4 @"
        import os
        version = VERSION_BASE + "+" + os.popen(command, mode='r').read()
    except OSError or ValueError or subprocess.TimeoutExpired:
        version = VERSION_BASE + "-unknown"
    return version


setuptools.setup(
    name='attic',  # it seems that doing that in setup.cfg doesn't work for me
    version=get_version(),
)
