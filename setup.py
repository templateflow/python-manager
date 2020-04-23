#!/usr/bin/env python
"""Setup TemplateFlow Manager."""
import sys
from setuptools import setup

if __name__ == "__main__":
    """ Install entry-point """
    extra_args = {}
    if "bdist_wheel" in sys.argv:
        extra_args["setup_requires"] = [
            "setuptools >= 42.0",
            "wheel",
            "setuptools_scm[toml] >= 3.4",
        ]
    setup(**extra_args)
