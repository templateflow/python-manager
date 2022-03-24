"""CLI."""
from os import cpu_count, getcwd, chdir, getenv
import datetime
import json
from pathlib import Path
import click
from tempfile import TemporaryDirectory
import toml
from pkg_resources import resource_filename as pkgr_fn


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
@click.option("--osf-user", envvar="OSF_USERNAME", callback=is_set)
@click.password_option(
    "--osf-password",
    envvar="OSF_PASSWORD",
    prompt="OSF password",
    confirmation_prompt=False,
)
@click.option("--osf-overwrite", is_flag=True)
@click.option(
    "--gh-user",
    envvar="GITHUB_USER",
)
@click.password_option(
    "--gh-token",
    prompt="GitHub personal authentication token",
    confirmation_prompt=False,
    envvar="GITHUB_TOKEN",
)
@click.option("--path", type=click.Path(exists=True))
@click.option("-j", "--nprocs", type=click.IntRange(min=1), default=cpu_count())
def add(
    template_id,
    osf_user,
    osf_password,
    osf_overwrite,
    gh_user,
    gh_token,
    path,
    nprocs,
):
    """Add a new template."""
    from .io import run_command
    from .utils import copy_template
    import shutil
    from datalad import api as dl

    gh_password = getenv("GITHUB_PASSWORD")
    if not gh_user or not gh_token:
        raise click.BadParameter("Insufficient secrets to login into GitHub")

    path = Path(path or f"tpl-{template_id}").absolute()
    cwd = Path.cwd()

    if not path.exists():
        raise click.UsageError(f"<{path}> does not exist.")

    metadata = {}

    # Check metadata
    if (path / "template_description.json").exists():
        metadata = json.loads((path / "template_description.json").read_text())
    metadata["Identifier"] = template_id

    # Check license
    license_path = path / "LICENSE"
    if not license_path.exists():
        license_path = path / "LICENCE"
    if not license_path.exists():
        license_path = path / "COPYING"

    if not license_path.exists():
        license_prompt = click.prompt(
            text="""\
A LICENSE file MUST be distributed with the template. The TemplateFlow Manager can \
set a license (either CC0 or CC-BY) for you.""",
            type=click.Choice(("CC0", "CC-BY", "Custom (abort)")),
            default="Custom (abort)",
        )
        if license_prompt == "Custom (abort)":
            raise click.UsageError(
                "Cannot proceed without a valid license. Please write a LICENSE "
                "file before uploading."
            )

        license_path = Path(pkgr_fn("tfmanager", f"data/{license_prompt}.LICENSE"))
        metadata["License"] = license_prompt

    # Check RRID
    if not metadata.get("RRID"):
        rrid = click.prompt(
            text="Has a RRID (research resource ID) already been assigned?",
            type=str,
            default=''
        ) or None

        if rrid:
            metadata["RRID"] = rrid

    # Check short description
    if not metadata.get("Name", "").strip():
        short_desc = click.prompt(
            text="""\
The "Name" metadata is not found within the <template_description.json> file. \
Please provide a short description for this resource.""",
            type=str,
        )

        if not short_desc:
            raise click.UsageError(
                "Cannot proceed without a short description."
            )

        metadata["Name"] = short_desc

    # Check authors
    authors_prompt = [a.strip() for a in metadata.get("Authors", []) if a.strip()]
    if not authors_prompt:
        authors_prompt = [
            n.strip() for n in click.prompt(
                text="""\
The "Authors" metadata is not found within the <template_description.json> file. \
Please provide a list of authors separated by semicolon (;) in <Lastname Initial(s)> format.""",
                type=str,
            ).split(";")
            if n
        ]
        if not authors_prompt:
            click.confirm("No authors were given, do you want to continue?", abort=True)

    metadata["Authors"] = authors_prompt

    # Check references
    refs_prompt = [
        f"""\
{'https://doi.org/' if not a.strip().startswith('http') else ''}\
{a.replace("doi:", "").strip()}"""
        for a in metadata.get("ReferencesAndLinks", []) if a.strip()
    ]
    if not refs_prompt:
        refs_prompt = [
            n.replace('"', "").strip() for n in click.prompt(
                text="""\
The "ReferencesAndLinks" metadata is not found within the <template_description.json> file. \
Please provide a list of links and publications within double-quotes \
(for example, "doi:10.1101/2021.02.10.430678") and separated by spaces (< >).""",
                type=str,
            ).split(" ")
            if n
        ]
        if not refs_prompt:
            click.confirm("No authors were given, do you want to continue?", abort=True)
    metadata["ReferencesAndLinks"] = refs_prompt

    with TemporaryDirectory() as tmpdir:
        repodir = Path(tmpdir) / "templateflow"

        # Clone root <user>/templateflow project - fork if necessary
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

        chdir(repodir)

        # Create datalad dataset
        dl.create(
            path=f"tpl-{template_id}",
            cfg_proc="text2git",
            initopts={"initial-branch": "main"},
            description=metadata["Name"],
        )

        # Populate template
        copy_template(
            path=path,
            dest=repodir / f"tpl-{template_id}",
        )
        # Copy license
        shutil.copy(license_path, repodir / f"tpl-{template_id}" / "LICENSE")
        # (Over)write template_description.json
        (repodir / f"tpl-{template_id}" / "template_description.json").write_text(
            json.dumps(metadata, indent=2)
        )
        # Init/update CHANGELOG
        changelog = repodir / f"tpl-{template_id}" / "CHANGES"
        changes = [f"""
## {datetime.date.today().ctime()} - TemplateFlow Manager Upload
Populated contents after NIfTI sanitizing by the TF Manager.

"""]
        if changelog.exists():
            changes += [changelog.read_text()]
        changelog.write_text("\n".join(changes))

        # Init OSF sibling
        rrid_str = f" (RRID: {metadata['RRID']})" if metadata.get("RRID") else ""
        dl.create_sibling_osf(
            title=f"TemplateFlow resource: <{template_id}>{rrid_str}",
            name="osf",
            dataset=f"./tpl-{template_id}",
            public=True,
            category="data",
            description=metadata["Name"],
            tags=["TemplateFlow dataset", template_id]
        )
        # Init GH sibling
        dl.create_sibling_github(
            reponame=f"tpl-{template_id}",
            dataset=str(repodir / f"tpl-{template_id}"),
            github_login=gh_user,
            publish_depends="osf-storage",
            existing="replace",
            access_protocol="ssh"
        )

        # Save added contents
        dl.save(
            dataset=str(repodir / f"tpl-{template_id}"),
            message="ADD: TemplateFlow Manager initialized contents"
        )

        # Push to siblings
        dl.push(
            dataset=str(repodir / f"tpl-{template_id}"),
            to="github",
            jobs=cpu_count(),
        )

        # Back home
        chdir(cwd)

        run_command(
            "git fetch upstream tpl-intake", cwd=str(repodir), capture_output=False,
        )
        run_command(
            f"git checkout -b pr/tpl-{template_id} upstream/tpl-intake",
            cwd=str(repodir),
            capture_output=False,
        )
        (repodir / f"{path.name}.toml").write_text(
            toml.dumps({"github": {"user": gh_user},})
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
            f"git push -u origin pr/tpl-{template_id}",
            cwd=str(repodir),
            capture_output=False,
            env={"GITHUB_USER": gh_user, "GITHUB_TOKEN": gh_token},
        )

        (repodir.parent / "message.md").write_text(
            f"""\
ADD: ``tpl-{template_id}``

## {metadata.get('Name', '<missing Name>')}

Identifier: {metadata.get('Identifier', '<missing Identifier>')}
Datalad: https://github.com/{gh_user}/tpl-{template_id}

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
            f"-h {gh_user}:pr/tpl-{template_id} "
            f"-F {repodir.parent / 'message.md'}",
            cwd=str(repodir),
            capture_output=False,
            env={"GITHUB_USER": gh_user, "GITHUB_TOKEN": gh_token},
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
@click.option("--force-dtype/--no-force-dtype", default=True)
@click.option("--deoblique/--no-deoblique", default=False)
def sanitize(template_dir, normalize, force_dtype, deoblique):
    """Check orientation and datatypes of NIfTI files in template folder."""
    from .utils import copy_template as _copy_template

    updated = _copy_template(template_dir, normalize, force_dtype, deoblique)
    if updated:
        print(
            "\n  * ".join(
                ["Modified:"] + [f"<{u.relative_to(template_dir)}>" for u in updated]
            )
        )


@cli.command()
@click.argument("template_id")
@click.argument("field")
@click.option("--path", type=click.Path(exists=True))
def metadata(template_id, field, path):
    """Get a metadata entry from a template."""
    import json
    if template_id.startswith("tpl-"):
        template_id = template_id[4:]
    path = Path(path or f"tpl-{template_id}")
    metadata = json.loads((path / "template_description.json").read_text())
    print(metadata.get(field))


if __name__ == "__main__":
    """ Install entry-point """
    cli()
