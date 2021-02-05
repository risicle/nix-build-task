{
  pkgs ? import (builtins.fetchTarball {
    url = "https://github.com/nixos/nixpkgs/archive/2b9daa020d40aac9d6ff3d1941d22acf4a3e9229.tar.gz";
    sha256 = "0kh2h5cbyxijy9i0mzmfzvma0qnp9zj0p3lbmy5imw2429jdpnx7";
  }) {}
}:

pkgs.dockerTools.buildImage {
  name = "nix-build-task";
  tag = "latest";

  fromImage = pkgs.dockerTools.pullImage {
    imageName = "nixos/nix";
    imageDigest = "sha256:a6bcef50c7ca82ca66965935a848c8c388beb78c9a5de3e3b3d4ea298c95c708";
    sha256 = "0z7dz3nxb2cd1fr2p92lp02l0rky3invcdl3rp12wqvskjrak5b3";
    os = "linux";
    arch = "x86_64";
  };

  config.Cmd = [
    (pkgs.writeScript "entrypoint.sh" ''
      #!${pkgs.bash}/bin/bash

      NIXFILE=${NIXFILE:-.}

      RESULT_PATH=$(${pkgs.nix}/bin/nix-build "$NIXFILE")

    '')
  ];
}

