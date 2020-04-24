"""CLI."""
from os import cpu_count
from pathlib import Path
import asyncio
import click
from functools import partial
from tempfile import TemporaryDirectory
import toml
import json


def _glob_all(path):
    for p in Path(path).iterdir():
        if p.name.startswith("."):
            continue
        if p.is_dir():
            yield from _glob_all(p)
        else:
            yield p


def run_command(cmd: str, env: dict = None, cwd: str = None, capture_output: bool = True) -> str:
    """
    Run prepared behave command in shell and return its output.

    :param cmd: Well-formed behave command to run.
    :return: Command output as string.
    """
    import os
    from subprocess import run
    if env:
        _env = dict(os.environ)
        _env.update(env)
        env = _env
    proc = run(
        cmd,
        capture_output=capture_output,
        shell=True,
        env=env,
        cwd=cwd,
    )
    return proc


@asyncio.coroutine
def run_command_on_loop(
    loop: asyncio.AbstractEventLoop,
    semaphore: asyncio.Semaphore,
    command: str,
    env: dict = None,
) -> bool:
    """
    Run test for one particular feature, check its result and return report.

    :param loop: Loop to use.
    :param command: Command to run.
    :return: Result of the command.
    """
    with (yield from semaphore):
        runner = partial(run_command, cmd=command, env=env)
        proc = yield from loop.run_in_executor(None, runner)
        filename = command.strip().split(' ')[-1]
        if proc.returncode == 0:
            message = f"Uploaded: {filename}"
        else:
            error = proc.stderr.decode()
            message = "ERROR:\n{error}"
            if "FileExistsError" in error:
                message = (f"WARNING: Did not overwrite <{filename}>, "
                           "please consider --osf-overwrite")
        print(message)
        return proc.returncode


@asyncio.coroutine
def run_all_commands(
    osf_cmd: str,
    osf_env: dict = None,
    path: Path = Path.cwd(),
    max_runners: int = 1,
) -> None:
    """
    Run all commands in a list.

    :param command_list: List of commands to run.
    """
    semaphore = asyncio.Semaphore(max_runners)

    loop = asyncio.get_event_loop()
    fs = [
        run_command_on_loop(
            loop,
            semaphore,
            f"{osf_cmd} {f} {f.relative_to(path.parent)}",
            osf_env,
        ) for f in _glob_all(path)
    ]
    for f in asyncio.as_completed(fs):
        yield from f


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
@click.option("-j", "--nprocs", type=click.IntRange(min=1),
              default=cpu_count())
def add(template_id, osf_project, osf_user, osf_password, osf_overwrite,
        gh_user, gh_password, path, nprocs):
    """Add a new template."""
    path = Path(path or f"tpl-{template_id}")

    if path.name != f"tpl-{template_id}":
        path = path / f"tpl-{template_id}"

    if not path.exists():
        raise click.UsageError(f"<{path}> does not exist.")

    descfile = path / "template_description.json"
    if not descfile.exists():
        raise FileNotFoundError(f"Missing template description <{descfile}>")

    metadata = json.loads(descfile.read_text())

    # click.echo("")
    osf_env = {
        "OSF_PROJECT": osf_project,
        "OSF_USERNAME": osf_user,
        "OSF_PASSWORD": osf_password,
    }
    loop = asyncio.get_event_loop()
    loop.run_until_complete(run_all_commands(
        osf_cmd=f"osf upload{' -f' * osf_overwrite}", path=path,
        osf_env=osf_env, max_runners=nprocs))

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
                env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password}
            )
            run_command(
                "hub fork --remote-name origin",
                cwd=str(repodir),
                capture_output=False,
                env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password}
            )

        run_command(
            "git remote add upstream https://github.com/templateflow/templateflow.git",
            cwd=str(repodir),
            capture_output=False,
        )
        run_command(
            "git fetch upstream tpl-intake",
            cwd=str(repodir),
            capture_output=False,
        )
        run_command(
            f"git checkout -b pr-tpl-{template_id.lower()} upstream/tpl-intake",
            cwd=str(repodir),
            capture_output=False,
        )
        (repodir / f"{path.name}.toml").write_text(toml.dumps({
            "osf": {"project": osf_project},
        }))
        run_command(
            f"git add {path.name}.toml",
            cwd=str(repodir),
            capture_output=False,
        )
        run_command(
            f"git commit -m 'add(tpl-{template_id}): create intake file'",
            cwd=str(repodir),
            capture_output=False,
        )
        run_command(
            f"git push -u origin pr-tpl-{template_id.lower()}",
            cwd=str(repodir),
            capture_output=False,
            env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password},
        )

        (repodir.parent / 'message.md').write_text(f"""\
ADD: ``tpl-{template_id}``

## {metadata.get('Name', '<missing Name>')}

Identifier: {metadata.get('Identifier', '<missing Identifier>')}
Storage: https://osf.io/{osf_project}/files/

### Authors
{', '.join(metadata['Authors'])}.

### License
{metadata.get('License', metadata.get('Licence', '<missing License>'))}

### Cohorts
{' '.join(('The dataset contains', len(metadata.get('cohort', []), 'cohorts.')))
 if metadata.get('cohort') else 'The dataset does not contain cohorts.'}

### References and links
{', '.join(metadata.get('ReferencesAndLinks', [])) or 'N/A'}

""")
        run_command(
            "hub pull-request -b templateflow:tpl-intake "
            f"-h {gh_user}:pr-tpl-{template_id.lower()} "
            f"-F {repodir.parent / 'message.md'}",
            cwd=str(repodir),
            capture_output=False,
            env={"GITHUB_USER": gh_user, "GITHUB_PASSWORD": gh_password},
        )


if __name__ == "__main__":
    """ Install entry-point """
    cli()
