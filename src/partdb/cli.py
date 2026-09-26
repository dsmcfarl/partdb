from importlib.metadata import version

import click


@click.group(name="partdb")
@click.version_option(version("partdb"))
def cli() -> None:
    """Manage workshop parts and locations."""
