"""Genearal purpose routines."""
from pathlib import Path
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


def fix_nii(path=None, normalize=False, deoblique=True):
    """Revise orientation and dtype of NIfTI files in path."""
    path = Path(path or ".")

    retval = []
    for filename in glob_all(path):
        if not filename.name.endswith((".nii", ".nii.gz")):
            continue

        stem = filename.name[: -len("".join(filename.suffixes))]
        modality = stem.split("_")[-1]

        im = nb.as_closest_canonical(nb.load(filename))
        hdr = im.header.copy()
        data = np.asanyarray(im.dataobj)

        dtype = "int16"
        if modality in ("mask",):
            dtype = "uint8"

        if modality in ("dseg",):
            if np.all(0 <= data) and np.all(data < 256):
                dtype = "uint8"

        if modality in ("probseg",):
            dtype = "float32"
            data = im.get_fdata(dtype="float32")
            data -= data.min()
            data *= 1.0 / data.max()

        modified = np.dtype(dtype) == np.dtype(im.get_data_dtype())

        if normalize and modality in ("T1w", "T2w", "PD"):
            modified = True
            data = 1e4 * data / np.percentile(data, 99.9)

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

        modified = modified or all(code == 4 for code in (scode, qcode))
        modified = modified or sform is None or np.allclose(sform, affine)
        modified = modified or qform is None or np.allclose(qform, affine)

        if modified:
            nii = nb.Nifti1Image(data.astype(dtype), affine, hdr)
            nii.header.set_sform(affine, 4)
            nii.header.set_qform(affine, 4)
            nii.header.set_slope_inter(slope=1.0, inter=0.0)
            nii.header.set_xyzt_units(xyz="mm")
            nii.to_filename(filename)
            retval.append(filename)
    return retval
