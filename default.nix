{
  pkgs ? import (import ./nix/sources.nix).nixpkgs {}
  , baseImage ? null
  , ...
}:

let
  # TODO use a lighter-weight base image
  baseImage_ = if baseImage != null then baseImage else pkgs.dockerTools.pullImage {
    imageName = "nixos/nix";
    imageDigest = "sha256:1e19753e8150c11afb8327d47595e41707c23cb36907539bb48cfa703821a2a8";
    sha256 = "054y3m1fwv1iiqckx17s7ldd1av6crmwypsmvjnqhy8vv0mic0gd";
    os = "linux";
    arch = "x86_64";
  };
in rec {
  image = pkgs.dockerTools.buildImage {
    name = "nix-build-task";
    tag = "latest";

    fromImage = baseImage_;

    contents = pkgs.runCommand "build" {
      buildInputs = [ pkgs.python3 pkgs.makeWrapper ];
      wrappedPath = pkgs.lib.makeBinPath (with pkgs; [
        cachix_stderr
        gnutar
        gzip
        nix
        oci-image-tool
        skopeo
        xz
      ]);
    } ''
      mkdir -p $out/bin
      cp ${./build.py} $out/bin/build
      wrapProgram $out/bin/build \
        --set PATH $wrappedPath
      patchShebangs $out/bin
    '';

    config.Cmd = [ "/bin/build" ];
  };
  # a custom version of cachix which won't output status messages to stdout, which
  # would get in the way of our use of the stdout to read build outputs
  cachix_stderr = pkgs.cachix.overrideAttrs (oldAttrs: {
    patchPhase = (if oldAttrs ? patchPhase then oldAttrs.patchPhase else "") + ''
      find ./ -type f -exec sed -i \
        -e 's|\bputText\b|putErrText|g' \
        -e 's|\bputStr\b|hPutStr stderr|g' \
        {} \;
    '';
  });
  bumpSources = pkgs.writeScript "bump-sources" ''
    #!${pkgs.bash}/bin/bash
    set -e

    ${pkgs.niv}/bin/niv update nixpkgs
  '';
  bumpSourcesImage = pkgs.dockerTools.buildImage {
    name = "nix-build-task-bump-sources";
    contents = pkgs.symlinkJoin {
      name = "contents";
      paths = with pkgs; [
        bash
        cacert
        git
        nix
        busybox
        (linkFarm "bump-sources-bin" [{name = "bin/bump-sources"; path = bumpSources;}])
      ];
    };
    config.Env = let
      crtFile = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    in [
      "GIT_SSL_CAINFO=${crtFile}"
      "NIX_SSL_CERT_FILE=${crtFile}"
    ];
  };
}
