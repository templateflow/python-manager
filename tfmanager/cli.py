"""CLI."""
from os import cpu_count, getcwd
from pathlib import Path
import click
from tempfile import TemporaryDirectory
import toml


def validate_name(ctx, param, value):
    """Check whether this template already exists in the Archive."""
    from templateflow.api import templates

    value = value[4:] if value.startswith("tpl-") else value
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
    return value


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
@click.option("--gh-user", envvar="GITHUB_USER", callback=is_set)
@click.password_option(
    "--gh-password",
    envvar="GITHUB_PASSWORD",
    prompt="GitHub password",
    confirmation_prompt=False,
)
@click.option("--path", type=click.Path(exists=True))
@click.option("-j", "--nprocs", type=click.IntRange(min=1), default=cpu_count())
def add(
    template_id,
    osf_project,
    osf_user,
    osf_password,
    osf_overwrite,
    gh_user,
    gh_password,
    path,
    nprocs,
):
    """Add a new template."""
    from .io import run_command
    from .osf import upload as _upload

    path = Path(path or f"tpl-{template_id}")

    if not path.exists():
        raise click.UsageError(f"<{path}> does not exist.")

    metadata = _upload(
        template_id, osf_project, osf_user, osf_password, osf_overwrite, path, nprocs,
    )

    with TemporaryDirectory() as tmpdir:
        repodir = Path(tmpdir) / "templateflow"
        click.echo(f"Preparing Pull-Request (wd={tmpdir}).")
        clone = run_command(
            f"git clone https://github.com/{gh_user}/templateflow.git "
            "--branch tpl-intake --single-branch",
            cwd=tmpdir,
            capture_output=False,
        )
        if clone.returncode != 0:
            run_command(
                "hub clone templateflow/templateflow",
                cwd=tmpdir,
                capture_output=False,
                env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password},
            )
            run_command(
                "hub fork --remote-name origin",
                cwd=str(repodir),
                capture_output=False,
                env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password},
            )
        else:
            run_command(
                "git remote add upstream https://github.com/templateflow/templateflow.git",
                cwd=str(repodir),
                capture_output=False,
            )

        run_command(
            "git fetch upstream tpl-intake", cwd=str(repodir), capture_output=False,
        )
        run_command(
            f"git checkout -b pr/{osf_project}/tpl-{template_id} upstream/tpl-intake",
            cwd=str(repodir),
            capture_output=False,
        )
        (repodir / f"{path.name}.toml").write_text(
            toml.dumps({"osf": {"project": osf_project},})
        )
        run_command(
            f"git add {path.name}.toml", cwd=str(repodir), capture_output=False,
        )
        run_command(
            f"git commit -m 'add(tpl-{template_id}): create intake file'",
            cwd=str(repodir),
            capture_output=False,
        )
        run_command(
            f"git push -u origin pr/{osf_project}/tpl-{template_id}",
            cwd=str(repodir),
            capture_output=False,
            env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password},
        )

        (repodir.parent / "message.md").write_text(
            f"""\
ADD: ``tpl-{template_id}``

## {metadata.get('Name', '<missing Name>')}

Identifier: {metadata.get('Identifier', '<missing Identifier>')}
Storage: https://osf.io/{osf_project}/files/

### Authors
{', '.join(metadata['Authors'])}.

### License
{metadata.get('License', metadata.get('Licence', '<missing License>'))}

### Cohorts
{' '.join(('The dataset contains', str(len(metadata.get('cohort', []))), 'cohorts.'))
 if metadata.get('cohort') else 'The dataset does not contain cohorts.'}

### References and links
{', '.join(metadata.get('ReferencesAndLinks', [])) or 'N/A'}

"""
        )
        run_command(
            "hub pull-request -b templateflow:tpl-intake "
            f"-h {gh_user}:pr/{osf_project}/tpl-{template_id} "
            f"-F {repodir.parent / 'message.md'}",
            cwd=str(repodir),
            capture_output=False,
            env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password},
        )


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
@click.option("-j", "--nprocs", type=click.IntRange(min=1), default=cpu_count())
def push(
    template_id, osf_project, osf_user, osf_password, osf_overwrite, path, nprocs,
):
    """Push a new template, but do not create PR."""
    from .osf import upload as _upload
    path = Path(path or f"tpl-{template_id}")

    if not path.exists():
        raise click.UsageError(f"<{path}> does not exist.")

    _upload(
        template_id, osf_project, osf_user, osf_password, osf_overwrite, path, nprocs,
    )


@cli.command()
@click.argument("template_id")
@click.option("--osf-project", envvar="OSF_PROJECT", callback=is_set)
@click.option("--overwrite", is_flag=True)
@click.option("--path", type=click.Path(exists=False))
@click.option("-j", "--nprocs", type=click.IntRange(min=1), default=cpu_count())
def get(
    template_id, osf_project, overwrite, path, nprocs,
):
    """Add a new template."""
    from .osf import get_template as _get
    if template_id.startswith("tpl-"):
        template_id = template_id[4:]

    path = Path(path or f"tpl-{template_id}")

    if path.name != f"tpl-{template_id}":
        path = path / f"tpl-{template_id}"

    if path.exists():
        click.echo(f"WARNING: <{path}> exists.")

    _get(template_id, osf_project, overwrite, path, nprocs)


@cli.command()
@click.argument("template_id")
@click.option("--osf-project", envvar="OSF_PROJECT", default="ue5gx")
@click.option("-o", "--out-csv", type=click.Path(exists=False))
def geturls(template_id, osf_project, out_csv):
    """Add a new template."""
    from .osf import get_project_urls

    if template_id.startswith("tpl-"):
        template_id = template_id[4:]

    urls = get_project_urls(
        f"""\
https://files.osf.io/v1/resources/{osf_project}/providers/osfstorage/\
""",
        f"tpl-{template_id}",
    )
    if out_csv:
        Path(out_csv).write_text(urls)
        return
    print(urls)


@cli.command()
@click.argument("template_dir", type=click.Path(exists=True), default=getcwd())
@click.option("--normalize/--no-normalize", default=True)
@click.option("--deoblique/--no-deoblique", default=False)
def sanitize(template_dir, normalize, deoblique):
    """Check orientation and datatypes of NIfTI files in template folder."""
    from .utils import fix_nii as _fix_nii

    updated = _fix_nii(template_dir, normalize, deoblique)
    if updated:
        print(
            "\n  * ".join(
                ["Modified:"] + [f"<{u.relative_to(template_dir)}>" for u in updated]
            )
        )


if __name__ == "__main__":
    """ Install entry-point """
    cli()
