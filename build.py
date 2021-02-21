#!/usr/bin/env python3
import itertools
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile


def _normalize_args():
    if os.environ.get("ATTR") and os.environ.get("ATTR0"):
        print(
            "nix-build-task: error: conflict: both $ATTR and $ATTR0 set",
            file=sys.stderr,
        )
        sys.exit(5)

    if os.environ.get("ATTR"):
        os.environ["ATTR0"] = os.environ["ATTR"]

    if os.environ.get("OUTPUT_PREPARE_IMAGE") and os.environ.get("OUTPUT0_PREPARE_IMAGE"):
        print(
            "nix-build-task: error: conflict: both $OUTPUT_PREPARE_IMAGE and $OUTPUT0_PREPARE_IMAGE set",
            file=sys.stderr,
        )
        sys.exit(5)

    if os.environ.get("OUTPUT_PREPARE_IMAGE"):
        os.environ["OUTPUT0_PREPARE_IMAGE"] = os.environ["OUTPUT_PREPARE_IMAGE"]

    os.environ["NIXFILE"] = os.environ.get("NIXFILE") or "."


def _handle_result_build(result_index, result_line, output_dir_path):
    src_path = pathlib.Path(result_line)
    result_path = output_dir_path / ("result" + ("" if result_index == 0 else f"-{result_index+1}"))

    if src_path.is_dir():
        shutil.copytree(src_path, result_path, symlinks=False, dirs_exist_ok=True)
    else:
        shutil.copy(src_path, result_path, follow_symlinks=True)


def _handle_result_evaldrv(result_index, result_line, output_dir_path):
    with open(output_dir_path / ("result" + ("" if result_index == 0 else f"-{result_index+1}")), "w") as f:
        f.write(result_line)


_sigs_offsets = {
    "gz": (b"\x1f\x8b", 0),
    "xz": (b"\xfd\x37\x7a\x58\x5a\x00", 0),
    "tar": (b"\x75\x73\x74\x61\x72", 0x101),
}
_sig_max_len_needed = max(offset + len(sig) for sig, offset in _sigs_offsets.values())


class _UnknownFileType(KeyError): pass


def _detect_file_type(file_path):
    with open(file_path, "rb") as f:
        file_head = f.read(_sig_max_len_needed)

    for type_name, (sig, offset) in _sigs_offsets.items():
        if file_head[offset:offset+len(sig)] == sig:
            return type_name
    else:
        raise _UnknownFileType


def _image_decompress(image_path):
    type_name = _detect_file_type(image_path)
    image_tar_path = image_path.parent / "image.tar"

    prog_names = {
        "gz": "gzip",
        "xz": "xz",
    }
    if type_name in prog_names:
        with open(image_tar_path, "wb") as fout:
            subprocess.run(
                (prog_names[type_name], "-dc", image_path),
                stdout=fout,
                check=True,
            )
    elif type_name == "tar":
        image_tar_path.symlink_to(os.path.relpath(image_path, start=image_tar_path.parent))
    else:
        raise _UnknownFileType

    return image_tar_path


def _image_inspect(image_tar_path):
    with tarfile.open(image_tar_path, "r:") as tf:
        image_tar_contents = tf.getnames()

    if "oci-layout" in image_tar_contents:
        image_type = "oci-archive"
    elif "manifest.json" in image_tar_contents:
        image_type = "docker-archive"
    else:
        raise _UnknownFileType

    inspect_result = subprocess.run(
        ("skopeo", "inspect", f"{image_type}:{image_tar_path}",),
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )

    return image_type, json.loads(inspect_result.stdout)


def _image_unpack(image_type, image_tar_path):
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(
            (
                "skopeo",
                "--insecure-policy",
                "copy",
                f"{image_type}:{image_tar_path}", 
                f"oci:{td}:latest",
            ),
            check=True,
        )
        rootfs_path = image_tar_path.parent / "rootfs"
        subprocess.run(
            (
                "oci-image-tool",
                "unpack",
                td,
                rootfs_path,
                "--ref",
                "name=latest",
            ),
            check=True,
        )
    return rootfs_path


def _post_output_hook_build(attr_index, output_dir_path):
    prepare_image = os.environ.get(f"OUTPUT{attr_index}_PREPARE_IMAGE")
    if prepare_image and prepare_image != "0":
        print(
            f"nix-build-task: preparing image for {output_dir_path}",
            file=sys.stderr,
        )

        try:
            image_tar_path = _image_decompress(output_dir_path / "result")
            image_type, inspect_dict = _image_inspect(image_tar_path)
        except _UnknownFileType:
            print(
                f"nix-build-task: error: unable to determine image type of {output_dir_path}",
                file=sys.stderr,
            )
            sys.exit(6)

        print(
            f"nix-build-task: image in {output_dir_path} appears to be {image_type!r}",
            file=sys.stderr,
        )

        with open(output_dir_path / "digest", "w") as f:
            f.write(inspect_dict.get("Digest"))

        if prepare_image.lower() == "unpack":
            print(
                f"nix-build-task: unpacking image for {output_dir_path}",
                file=sys.stderr,
            )
            with open(output_dir_path / "metadata.json", "w") as f:
                json.dump({
                    "env": inspect_dict.get("Env"),
                    "user": inspect_dict.get("User"),
                }, f)

            _image_unpack(image_type, image_tar_path)


_nop_func = lambda *args, **kwargs: None


def _main(nix_command_stem, handle_result_func, post_output_hook):
    for attr_index in itertools.takewhile(
        lambda i: os.environ.get(f"ATTR{i}") or not i,
        itertools.count(),
    ):
        attr = os.environ.get(f"ATTR{attr_index}")
        if not (attr or attr_index):
            attr = os.environ.get("ATTR")
        for_attr_text = f" for attr {attr!r}" if attr else ""

        print(
            f"nix-build-task: running {nix_command_stem[0]}{for_attr_text}",
            file=sys.stderr,
        )
        result_list = subprocess.run(
            nix_command_stem + (os.environ["NIXFILE"],) + (("-A", attr,) if attr else ()),
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        )

        output_dir_path = pathlib.Path(f"output{attr_index}")
        if attr_index == 0 and not output_dir_path.is_dir():
            output_dir_path = pathlib.Path("output")

        if not output_dir_path.is_dir():
            print(
                f"nix-build-task: warning: missing output {output_dir_path}, "
                f"nowhere to put results{for_attr_text}",
                file=sys.stderr,
            )
        else:
            print(
                f"nix-build-task: copying results{for_attr_text} to {output_dir_path}",
                file=sys.stderr,
            )
            for result_index, _result_line in enumerate(result_list.stdout.splitlines()):
                result_line = _result_line.strip()
                if result_line:
                    handle_result_func(result_index, result_line, output_dir_path)

            post_output_hook(attr_index, output_dir_path)


if __name__ == "__main__":
    _normalize_args()

    if len(sys.argv) >= 2 and sys.argv[1] == "eval-drv":
        nix_command_stem = ("nix-instantiate", "--eval",)
        handle_result_func = _handle_result_evaldrv
        post_output_hook = _nop_func
    else:
        nix_command_stem = ("nix-build",)
        handle_result_func = _handle_result_build
        post_output_hook = _post_output_hook_build

    _main(nix_command_stem, handle_result_func, post_output_hook)
