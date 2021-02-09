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
  nix-build-task-lib = import ./lib.nix { inherit pkgs; };
in rec {
  image = pkgs.dockerTools.buildImage {
    name = "nix-build-task";
    tag = "latest";

    fromImage = baseImage_;

    contents = (pkgs.writeScriptBin "build" ''
      #!${pkgs.bash}/bin/bash
      set -e

      NIXFILE=''${NIXFILE:-.}
      OUTPUT=''${OUTPUT:-output}
      ATTR_ARG=''${ATTR:+-A $ATTR}

      ${pkgs.nix}/bin/nix-build "$NIXFILE" $ATTR_ARG > result_list
      echo "Built $(cat result_list)"
      cp -Lr $(head -n 1 result_list)/* "$OUTPUT/"
    '');

    config.Cmd = [ "/bin/build" ];
  };
  imageConcourse = nix-build-task-lib.concourseStyleImageOutput image;
  bumpSources = pkgs.writeScript "bump-sources" ''
    #!${pkgs.bash}/bin/bash
    set -e

    ${pkgs.niv}/bin/niv update nixpkgs
  '';
}
