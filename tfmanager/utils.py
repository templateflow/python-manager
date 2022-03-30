"""Genearal purpose routines."""
import shutil
from pathlib import Path
from contextlib import suppress
from typing import Union, Generator
import numpy as np
import nibabel as nb


def glob_all(path: Union[Path, str]) -> Generator[Path, None, None]:
    """Return all files in a tree recursively, skipping dot folders."""
    for p in Path(path).iterdir():
        if p.name.startswith("."):
            continue
        if p.is_dir():
            yield from glob_all(p)
        else:
            yield p


def copy_template(
    path=None, normalize=False, deoblique=True, force_dtype=True, dest=None
):
    """Revise orientation and dtype of NIfTI files in path."""
    path = Path(path or ".")
    dest = dest or path

    retval = []

    for filename in glob_all(path):
        relname = filename.relative_to(path)
        destname = dest / relname
        destname.parent.mkdir(parents=True, exist_ok=True)
        if not filename.name.endswith((".nii", ".nii.gz")):
            with suppress(shutil.SameFileError):
                shutil.copy(filename, destname)
            print(f"Copied: {relname} -> {destname}")
            continue

        stem = filename.name[: -len("".join(filename.suffixes))]
        modality = stem.split("_")[-1]

        im = nb.as_closest_canonical(nb.load(filename))
        hdr = im.header.copy()
        data_dtype = im.get_data_dtype()
        data = np.asanyarray(im.dataobj, dtype=data_dtype)

        dtype = "int16"
        if modality in ("mask",):
            dtype = "uint8"
        elif modality in ("dseg",) and np.all(0 <= data) and np.all(data < 256):
            dtype = "uint8"
        elif not force_dtype:
            dtype = data_dtype

        modified = np.dtype(dtype) != np.dtype(data_dtype)

        if modality in ("probseg",):
            modified = True
            dtype = "float32"
            data = im.get_fdata(dtype="float32")
            data -= data.min()
            data *= 1.0 / data.max()

        elif modified and normalize and modality in ("T1w", "T2w", "PD"):
            data = np.round(1e4 * im.get_fdata() / np.percentile(data, 99.9)).astype(dtype)

        affine = im.affine.copy()
        hdr.set_data_dtype(dtype)

        if deoblique and np.any(nb.affines.obliquity(affine) > 1e-2):
            modified = True
            card = np.diag(im.header.get_zooms()[:3])
            cardrot = affine[:3, :3].dot(np.linalg.inv(card))
            # If center of coordinates not at volume's center
            # do not modify its relative location w.r.t. data
            affine = np.linalg.inv(cardrot).dot(affine)
            affine[:3, :3] = card  # round off-diagonal elements

        sform, scode = im.header.get_sform(coded=True)
        qform, qcode = im.header.get_qform(coded=True)

        if (
            modified
            or not all(code == 4 for code in (scode, qcode))
            or sform is None
            or not np.allclose(sform, affine)
            or qform is None
            or not np.allclose(qform, affine)
        ):
            nii = nb.Nifti1Image(data.astype(dtype), affine, hdr)
            nii.header.set_sform(affine, 4)
            nii.header.set_qform(affine, 4)
            nii.header.set_slope_inter(slope=1.0, inter=0.0)
            nii.header.set_xyzt_units(xyz="mm")
            nii.to_filename(destname)
            print(f"Fixed NIfTI headers: {relname} -> {destname}")
            retval.append(filename)
        elif filename != destname:
            shutil.copy(filename, destname)
            print(f"Copied: {relname} -> {destname}")
        else:
            print(f"File {filename} not modified.")

    return retval
