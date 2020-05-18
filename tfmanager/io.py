"""I/O support."""
import asyncio
from functools import partial
from typing import Sequence, Mapping
from pathlib import Path
from .utils import glob_all as _glob_all


def run_command(
    cmd: str,
    env: Mapping[str, str] = None,
    cwd: str = None,
    capture_output: bool = True,
) -> str:
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

    proc = run(cmd, capture_output=capture_output, shell=True, env=env, cwd=cwd,)
    return proc


@asyncio.coroutine
def run_all(
    cmd_list: Sequence[str],
    env: Mapping[str, str] = None,
    cwd: Path = Path.cwd(),
    max_runners: int = 1,
) -> None:
    """
    Run all commands in a list.

    :param command_list: List of commands to run.
    """
    semaphore = asyncio.Semaphore(max_runners)

    loop = asyncio.get_event_loop()
    fs = [run_command_on_loop(loop, semaphore, cmd, env) for cmd in cmd_list]
    for f in asyncio.as_completed(fs):
        yield from f


@asyncio.coroutine
def run_command_on_loop(
    loop: asyncio.AbstractEventLoop,
    semaphore: asyncio.Semaphore,
    command: str,
    env: Mapping[str, str] = None,
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
        filename = proc.args.split(" ")[-1]
        is_fetch = "fetch" in proc.args.split(" ")
        if proc.returncode == 0:
            message = f"{['Uploaded', 'Fetched'][is_fetch]}: {filename}"
        else:
            error = proc.stderr.decode()
            message = f"ERROR:\n{error}"
            if "FileExistsError" in error or "already exists" in error:
                message = (
                    f"WARNING: Did not overwrite <{filename}>, "
                    f"please consider --{'osf-' * ~is_fetch}overwrite"
                )
        print(message)
        return proc.returncode


@asyncio.coroutine
def upload_all(
    osf_cmd: str,
    osf_env: Mapping[str, str] = None,
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
            loop, semaphore, f"{osf_cmd} {f} {f.relative_to(path.parent)}", osf_env,
        )
        for f in _glob_all(path)
    ]
    for f in asyncio.as_completed(fs):
        yield from f
