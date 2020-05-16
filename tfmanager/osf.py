"""Recursive datalad downloader for OSF."""
import json
import requests

OSF_EXTENSIONS = (".nii", ".nii.gz", ".gii")


def _osf_get(url):
    r = requests.get(url)
    if not r.ok:
        raise RuntimeError(f"Request <{url}>: ERROR {r.status_code}")

    return json.loads(r.content)["data"]


def _osf_getpath(obj, parents=None):
    parents = parents or []
    if (
        obj['attributes']['kind'] == 'file'
        and obj['attributes']['name'].endswith(OSF_EXTENSIONS)
    ):
        yield ",".join((
            "/".join(parents + [obj['attributes']['name']]),
            obj['links']['download'],
        ))
    elif obj['attributes']['kind'] == 'folder':
        parents += [obj['attributes']['name']]
        subdata = _osf_get(obj['links']['move'])
        for subitem in subdata:
            yield from _osf_getpath(subitem, parents=parents)


def get_project_urls(url, template_id, out_file=None):
    """Download the JSON metadata at the target URL into a python dictionary."""
    for folder in _osf_get(url):
        if folder['attributes']['name'] == template_id:
            template_url = folder['links']['move']
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

    return "\n".join(['name,link'] + sorted(hits))
