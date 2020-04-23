# emacs: -*- mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
"""TemplateFlow is the Zone of Templates."""
__packagename__ = "tfmanager"
__copyright__ = "2020, The TemplateFlow developers"
try:
    from ._version import __version__
except ModuleNotFoundError:
    from pkg_resources import get_distribution, DistributionNotFound

    try:
        __version__ = get_distribution(__packagename__).version
    except DistributionNotFound:
        __version__ = "unknown"
    del get_distribution
    del DistributionNotFound

__all__ = [
    "__copyright__",
    "__packagename__",
    "__version__",
]
