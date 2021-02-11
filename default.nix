{
  pkgs ? import (import ./nix/sources.nix).nixpkgs {}
  , baseImage ? null
  , ...
}:

let
  # TODO use a lighter-weight base image
  baseImage_ = if baseImage != null then baseImage else pkgs.dockerTools.pullImage {
    imageName = "nixos/nix";
    imageDigest = "sha256:a6bcef50c7ca82ca66965935a848c8c388beb78c9a5de3e3b3d4ea298c95c708";
    sha256 = "0z7dz3nxb2cd1fr2p92lp02l0rky3invcdl3rp12wqvskjrak5b3";
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
  bumpSources = pkgs.writeScriptBin "bump-sources" ''
    #!${pkgs.bash}/bin/bash
    set -e

    ${pkgs.niv}/bin/niv update nixpkgs
  '';
}
