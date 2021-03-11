# nix-build-task

This is a reusable task (in the vein of
[oci-build-task](https://github.com/vito/oci-build-task)) for building
[Nix](https://nixos.org/) derivations in [Concourse](https://concourse-ci.org/)
pipelines.

## Features

- Image-handling support. Container images produced by the derivations (through
  `dockerTools` or other means) can be used interchangably with those produced by
  `oci-build-task`. This includes being `put` to the `registry-image` resource or
  used immediately as a subsequent task image.
- [Cachix](https://cachix.org/) support. Push and pull, allowing unneccessary rebuilds
  to be avoided.
- Outpath evaluation mode, making it possible to detect when changes will actually
  result in a different build output without performing the build.

## Operation

The idea of `nix-build-task` is to aid in producing reproducible builds of your
projects, and in that spirit `nix-build-task` tries to be as "hands-off" as possible
with the nix expression it is building. The expectation is that expressions are
self-contained and strictly bring-your-own-nixpkgs. This way the same build result can
be reliably achieved just as easily with or without `nix-build-task`, on a remote server
or on a local development machine. See the guide on
[pinning nixpkgs](https://nixos.org/guides/towards-reproducibility-pinning-nixpkgs.html)
for more detail on how to achieve this.

An basic example task:

```yaml
  - task: build-my-project
    image: nix-build-task-dockerhub
    config:
      platform: linux
      image_resource:
        type: registry-image
        source:
          repository: risicle/nix-build-task
      inputs:
        - name: my-project-git
      outputs:
        - name: built-project
          path: output
      params:
        NIXFILE: my-project-git/project.nix
        ATTR: foo
      run:
        path: /bin/build
```

`nix-build-task` will call `nix-build` on the file pointed to in the `NIXFILE` parameter,
optionally targeting a specific attribute of that expression indicated by the `ATTR`
parameter, and attempt to copy the `result`s to an output at the path `output`. The
original nix output path of the derivation is written to `output/result.outpath`.
Multiple attributes can be specified as `ATTR0` ... `ATTR<n>` and their results will be
copied to the respective output paths `output0` ... `output<n>`. `/bin/build` is the
entry point to call in the `run.path`.

## Params

- `NIXFILE` (required): path to file containing nix expression.
- `ATTR0` ... `ATTR<n>`: attributes to build. `result`s will be copied to `output0` ...
  `output<n>`. `ATTR` is an alias of `ATTR0` and `output` is used for results if
  `output0` is not found.
- `OUTPUT0_PREPARE_IMAGE` ... `OUTPUT<n>_PREPARE_IMAGE`: set to a non-empty, non-`0`
  value, will cause the result from the respective output to be prepared as a container
  image to be used by e.g. concourse's `registry-image` resource. Set to the value
  `unpack`, will go a step further and prepare the image for immediate use as a concourse
  task image, equivalent to `oci-build-task`'s `UNPACK_ROOTFS` option.
  `OUTPUT_PREPARE_IMAGE` is an alias of `OUTPUT0_PREPARE_IMAGE`.
- `BUILD_ARG_<argname>`: passed to `nix-build`'s `--arg` option, specifying an argument
  to be passed to be nix expression in `NIXFILE`. Value interpreted as a nix expression.
- `BUILD_ARGSTR_<argname>`: passed to `nix-build`'s `--argstr` option, specifying an
  argument to be passed to be nix expression in `NIXFILE`. Value interpreted as a string.
- `NIX_OPTION_<optname>`: passed to `nix-build`'s `--option` argument, allows overriding
  a Nix configuration option.
- `CACHIX_CACHE`: name of the [Cachix](https://cachix.org/) cache to attempt to pull
  prebuilt binaries from and, if `CACHIX_CONF` or `CACHIX_SIGNING_KEY` are set, attempt
  to push to.
- `CACHIX_CONF`: path to a `cachix.dhall` file with credentials for cachix cache.

Not explicitly handled by `nix-build-task`, but just happen to work by virtue of being
passed as environment variables:

- `CACHIX_SIGNING_KEY`: key for signing packages being pushed to `CACHIX_CACHE`.
- `NIX_CONF_DIR`: can be used to point at your own supplied `nix.conf` for overriding
  many nix options at once. If you're going to do this, note that the `CACHIX_CACHE`
  parameter will put its settings in `/etc/nix/nix.conf` and if you want this to still
  have an effect you will want to use an `include` line to refer to it or manually
  include your own equivalent settings.
