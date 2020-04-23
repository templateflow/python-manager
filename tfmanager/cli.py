"""CLI."""
import click
from pathlib import Path


def validate_name(ctx, param, value):
    """Check whether this template already exists in the Archive."""
    from templateflow.api import templates

    value = value.lstrip("tpl-")
    if value in templates():
        raise click.BadParameter(
            f"A template with name {value} already exists in the Archive."
        )
    return value


def is_set(ctx, param, value):
    """Check that an argument is set."""
    if not value:
        raise click.BadParameter(
            f"Please set it explicitly or define the corresponding environment variable."
        )


@click.group()
@click.version_option(message="TF Archive manager %(version)s")
def cli():
    """The TemplateFlow Archive manager assists you in adding and updating templates."""
    pass


@cli.command()
@click.argument("template_id", callback=validate_name)
@click.option("--osf-project", envvar="OSF_PROJECT", callback=is_set)
@click.option("--osf-user", envvar="OSF_USERNAME", callback=is_set)
@click.password_option(
    "--osf-password",
    envvar="OSF_PASSWORD",
    prompt="OSF password",
    confirmation_prompt=False,
)
@click.option("--osf-overwrite", is_flag=True)
@click.option("--path", type=click.Path(exists=True))
def add(template_id, osf_project, osf_user, osf_password, osf_overwrite, path):
    """Add a new template."""
    if path is None:
        path = Path(f"tpl-{template_id}")

        if not path.exists():
            raise click.UsageError(f"<{path}> does not exist.")
    pass


if __name__ == "__main__":
    """ Install entry-point """
    cli()
