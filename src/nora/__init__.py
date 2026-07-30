from importlib.metadata import PackageNotFoundError, version


__all__ = ['__version__']


try:
    # Read from the metadata of the installed package rather than being
    # hardcoded here, so that cutting a release means bumping
    # `pyproject.toml` and not hunting down a third copy of the number
    __version__ = version('nora')
except PackageNotFoundError:
    # A source checkout that was never installed, which is how the test
    # suite runs
    __version__ = 'unknown'
