#!/usr/bin/env python3
import functools
import itertools
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile


_false_strs = ("0", "false",)


def _get_env_vars_with_prefix(prefix):
    return {
        k[len(prefix):]: v
        for k, v in os.environ.items()
        if k.startswith(prefix) and len(k) > len(prefix)
    }


def _get_build_args():
    return _get_env_vars_with_prefix("BUILD_ARG_")


def _get_build_argstrs():
    return _get_env_vars_with_prefix("BUILD_ARGSTR_")


def _get_nix_options():
    return _get_env_vars_with_prefix("NIX_OPTION_")


def _normalize_args():
    os.environ["HOME"] = os.getcwd()

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

    if os.environ.get("OUTPUT_EXPORT_NAR") and os.environ.get("OUTPUT0_EXPORT_NAR"):
        print(
            "nix-build-task: error: conflict: both $OUTPUT_EXPORT_NAR and $OUTPUT0_EXPORT_NAR set",
            file=sys.stderr,
        )
        sys.exit(5)

    if os.environ.get("OUTPUT_EXPORT_NAR"):
        os.environ["OUTPUT0_EXPORT_NAR"] = os.environ["OUTPUT_EXPORT_NAR"]

    os.environ["NIXFILE"] = os.environ.get("NIXFILE") or "."

    arg_conflicts = _get_build_args().keys() & _get_build_argstrs().keys()
    if arg_conflicts:
        print(
            "nix-build-task: error: conflict: both BUILD_ARG_ and BUILD_ARGSTR_ set"
            f" for arguments: {', '.join(arg_conflicts)}",
            file=sys.stderr,
        )
        sys.exit(5)

    if os.environ.get("NIX_LOG_DIR"):
        # NIX_LOG_DIR doesn't support relative paths but concourse users can't
        # predict the working directory of a task beforehand, so can't practically
        # point it at an output. make relative paths absolute.
        nix_log_dir = pathlib.Path(os.environ["NIX_LOG_DIR"])
        if not nix_log_dir.is_absolute():
            os.environ["NIX_LOG_DIR"] = str(nix_log_dir.resolve())


def _handle_result_build(result_index, result_line, output_dir_path):
    src_path = pathlib.Path(result_line)
    result_path = output_dir_path / ("result" + ("" if result_index == 0 else f"-{result_index+1}"))

    if src_path.is_dir():
        shutil.copytree(src_path, result_path, symlinks=False, dirs_exist_ok=True)
    else:
        shutil.copy(src_path, result_path, follow_symlinks=True)

    with open(str(result_path) + ".outpath", "w") as f:
        f.write(result_line)


def _handle_result_evaloutpaths(result_index, result_line, output_dir_path):
    print(
        f"nix-build-task: determining outpath for drv {result_line!r}",
        file=sys.stderr,
    )
    split_result_line = result_line.split("!")
    store_result = subprocess.run(
        ("nix-store", "--query", "--outputs", split_result_line[0],),
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )

    outpaths = tuple(x for x in store_result.stdout.splitlines() if x)
    if len(outpaths) == 1:
        outpath = outpaths[0]
    elif len(split_result_line) > 1:
        # choosing the longest matching line in case root derivation name happens to
        # end in `-{out name}` too
        outpath = max(
            (op for op in outpaths if op.endswith(f"-{split_result_line[-1]}")),
            key=lambda op: len(op),
        )
    else:
        # choosing the shortest matching line as it's presumably the default out
        outpath = min(outpaths, key=lambda op: len(op))

    with open(
        output_dir_path / (
            "result" + ("" if result_index == 0 else f"-{result_index+1}") + ".outpath"
        ),
        "w",
    ) as f:
        f.write(outpath)


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
                "umoci",
                "raw",
                "unpack",
                "--image",
                td,
                rootfs_path,
            ),
            check=True,
        )
    return rootfs_path


def _post_output_hook_build(attr_index, output_dir_path):
    prepare_image = os.environ.get(f"OUTPUT{attr_index}_PREPARE_IMAGE")
    if prepare_image and prepare_image.lower() not in _false_strs:
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

    export_nar = os.environ.get(f"OUTPUT{attr_index}_EXPORT_NAR")
    if export_nar and export_nar.lower() not in _false_strs:
        print(
            f"nix-build-task: exporting nar for {output_dir_path}",
            file=sys.stderr,
        )
        outpaths = tuple(sorted(
            outpath_file.read_text().strip()
            for outpath_file in output_dir_path.glob("*.outpath")
        ))

        if export_nar.lower() == "runtime-closure":
            print(
                "nix-build-task: calculating runtime closure of results in"
                f" {output_dir_path}",
                file=sys.stderr,
            )
            result_outpath_fns = subprocess.run(
                ("nix-store", "-qR",) + outpaths,
                stdout=subprocess.PIPE,
                text=True,
                check=True,
            )

            outpaths = tuple(sorted(
                x for x in (ofn.strip() for ofn in result_outpath_fns.stdout.splitlines())
                if x
            ))

        nar_path = output_dir_path / "result.nar"
        with open(nar_path, "wb") as fout:
            print(
                f"nix-build-task: exporting {nar_path}",
                file=sys.stderr,
            )
            subprocess.run(
                ("nix-store", "--export",) + outpaths,
                stdout=fout,
                check=True,
            )


def _attr_match_number(candidate):
    m = re.fullmatch(r"ATTR(\d+)", candidate)
    return (m or 0) and int(m.group(1))


def _main(nix_command_stem, nix_command_display, handle_result_func, post_output_hooks):
    arg_args = tuple(itertools.chain.from_iterable(
        ("--arg", k, v,)
        for k, v in _get_build_args().items()
    ))
    argstr_args = tuple(itertools.chain.from_iterable(
        ("--argstr", k, v,)
        for k, v in _get_build_argstrs().items()
    ))
    nix_option_args = tuple(itertools.chain.from_iterable(
        ("--option", k, v,)
        for k, v in _get_nix_options().items()
    ))

    common_args = (os.environ["NIXFILE"],) + arg_args + argstr_args + nix_option_args

    for attr_index in itertools.takewhile(
        lambda i: os.environ.get(f"ATTR{i}") or not i,
        itertools.count(),
    ):
        attr = os.environ.get(f"ATTR{attr_index}")
        for_attr_text = f" for attr {attr!r}" if attr else ""

        print(
            f"nix-build-task: running {nix_command_display}{for_attr_text}",
            file=sys.stderr,
        )
        result_list = subprocess.run(
            nix_command_stem + common_args + (("-A", attr,) if attr else ()),
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

            for hook in post_output_hooks:
                hook(attr_index, output_dir_path)

    unreached_attr_keys = sorted(
        k for k in os.environ.keys() if _attr_match_number(k) > attr_index
    )
    if unreached_attr_keys:
        print(
            f"nix-build-task: warning: ignoring params {', '.join(unreached_attr_keys)}: "
            f"evaluation stopped when ATTR{attr_index+1} was not found",
            file=sys.stderr,
        )


def _cachix_push_output_hook(
    cachix_cache,
    cachix_extra_args,
    cachix_push_extra_args,
    attr_index,
    output_dir_path,
):
    print(
        f"nix-build-task: pushing results for {output_dir_path} to cachix",
        file=sys.stderr,
    )
    for result_outpath_fn in output_dir_path.glob("result*.outpath"):
        with open(result_outpath_fn, "r") as f:
            outpath = f.read().strip()

        subprocess.run(
            (
                "cachix",
            ) + cachix_extra_args + (
                "push",
            ) + cachix_push_extra_args + (
                cachix_cache,
                outpath,
            ),
            check=True,
        )


def _init_cachix():
    cachix_cache = os.environ.get("CACHIX_CACHE")
    cachix_conf = os.environ.get("CACHIX_CONF")
    cachix_signing_key = os.environ.get("CACHIX_SIGNING_KEY")
    cachix_auth_token = os.environ.get("CACHIX_AUTH_TOKEN")
    cachix_push = os.environ.get("CACHIX_PUSH")
    cachix_push_extra_args = tuple(
        shlex.split(os.environ.get("CACHIX_PUSH_EXTRA_ARGS", ""))
    )

    cachix_extra_args = ()
    command_prefix = ()
    post_output_hooks = ()

    if cachix_conf:
        cachix_extra_args = cachix_extra_args + ("-c", cachix_conf,)

    if cachix_cache:
        print(
            f"nix-build-task: preparing cachix to use cache {cachix_cache!r}",
            file=sys.stderr,
        )
        subprocess.run(
            (
                "cachix",
            ) + cachix_extra_args + (
                "use",
                cachix_cache,
            ),
            check=True,
        )

        if not cachix_push:
            cachix_push = str(bool(
                cachix_conf or cachix_signing_key or cachix_auth_token
            ))

        if cachix_push.lower() == "outputs":
            post_output_hooks = post_output_hooks + (
                functools.partial(
                    _cachix_push_output_hook,
                    cachix_cache,
                    cachix_extra_args,
                    cachix_push_extra_args,
                ),
            )
        elif cachix_push.lower() not in _false_strs:
            command_prefix = command_prefix + (
                "cachix",
            ) + cachix_extra_args + (
                "watch-exec",
            ) + cachix_push_extra_args + (
                cachix_cache,
                "--",
            )

    return command_prefix, post_output_hooks


if __name__ == "__main__":
    _normalize_args()

    if len(sys.argv) >= 2 and sys.argv[1] == "eval-outpaths":
        nix_command_stem = ("nix-instantiate",)
        nix_command_display = "nix-instantiate"
        handle_result_func = _handle_result_evaloutpaths
        post_output_hooks = ()
    else:
        cachix_prefix, cachix_hooks = _init_cachix()
        nix_command_stem = cachix_prefix + ("nix-build",)
        nix_command_display = "nix-build"
        handle_result_func = _handle_result_build
        post_output_hooks = (_post_output_hook_build,) + tuple(cachix_hooks)

    _main(nix_command_stem, nix_command_display, handle_result_func, post_output_hooks)
