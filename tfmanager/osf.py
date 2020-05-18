"""Recursive datalad downloader for OSF."""
import json
from pathlib import Path
import asyncio
import requests
from .io import upload_all, run_command, run_all


OSF_EXTENSIONS = (".nii", ".nii.gz", ".gii")


def _osf_get(url):
    r = requests.get(url)
    if not r.ok:
        raise RuntimeError(f"Request <{url}>: ERROR {r.status_code}")

    return json.loads(r.content)["data"]


def _osf_getpath(obj, parents=None):
    parents = parents or []
    if obj["attributes"]["kind"] == "file" and obj["attributes"]["name"].endswith(
        OSF_EXTENSIONS
    ):
        yield ",".join(
            ("/".join(parents + [obj["attributes"]["name"]]), obj["links"]["download"],)
        )
    elif obj["attributes"]["kind"] == "folder":
        parents += [obj["attributes"]["name"]]
        subdata = _osf_get(obj["links"]["move"])
        for subitem in subdata:
            yield from _osf_getpath(subitem, parents=parents)


def get_project_urls(url, template_id, out_file=None):
    """Download the JSON metadata at the target URL into a python dictionary."""
    for folder in _osf_get(url):
        if folder["attributes"]["name"] == template_id:
            template_url = folder["links"]["move"]
            break
    else:
        raise RuntimeError(f"Template <{template_id}> not found.")

    hits = []
    for p in _osf_get(template_url):
        hit = _osf_getpath(p)
        if hit is None:
            continue

        if isinstance(hit, str):
            hits.append(hit)
        else:
            hits += [h for h in hit if h]

    return "\n".join(["name,link"] + sorted(hits))


def upload(
    template_id, osf_project, osf_user, osf_password, osf_overwrite, path, nprocs,
):
    """Upload template to OSF."""
    if path.name != f"tpl-{template_id}":
        path = path / f"tpl-{template_id}"

    descfile = path / "template_description.json"
    if not descfile.exists():
        raise FileNotFoundError(f"Missing template description <{descfile}>")

    osf_env = {
        "OSF_PROJECT": osf_project,
        "OSF_USERNAME": osf_user,
        "OSF_PASSWORD": osf_password,
    }
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        upload_all(
            osf_cmd=f"osf upload{' -f' * osf_overwrite}",
            path=path,
            osf_env=osf_env,
            max_runners=nprocs,
        )
    )
    return json.loads(descfile.read_text())


def get_template(template_id, osf_project, overwrite, path, nprocs):
    """Get full template."""
    osf_env = {
        "OSF_PROJECT": osf_project,
    }
    remote_list = (
        run_command("osf list", env=osf_env, capture_output=True,)
        .stdout.decode()
        .splitlines()
    )
    osf_prefix = f"osfstorage/tpl-{template_id}/"
    remote_list = [Path(fname) for fname in remote_list if fname.startswith(osf_prefix)]
    dest_files = [(path / fname.relative_to(Path(osf_prefix))) for fname in remote_list]

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        run_all(
            cmd_list=[
                f"osf fetch{' -f' * overwrite} {remote_file} {local_file}"
                for remote_file, local_file in zip(remote_list, dest_files)
            ],
            env=osf_env,
            max_runners=nprocs,
        )
    )
