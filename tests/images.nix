{
  pkgs ? import (import ../nix/sources.nix).nixpkgs {}
  , ...
}:

rec {
  cf-cli-shell = pkgs.dockerTools.buildImage {
    name = "cf-cli-shell";
    tag = "1.2.3";

    contents = pkgs.symlinkJoin {
      name = "contents";
      paths = [
        pkgs.bash
        pkgs.cloudfoundry-cli
      ];
    };

    config.Env = [
      "CF_USERNAME=foo"
    ];
  };
  alpine-fetched = pkgs.dockerTools.pullImage {
    imageName = "alpine";
    imageDigest = "sha256:4661fb57f7890b9145907a1fe2555091d333ff3d28db86c3bb906f6a2be93c87";
    sha256 = "053ja4s6bqamjs758x2yrzxym00qjq4c4ij2cdz0xxgqd7h06ijw";
    os = "linux";
    arch = "x86_64";
  };
  skopeo-alone = let
    image = pkgs.dockerTools.buildImage {
      name = "skopeo";
      tag = "bar";

      contents = pkgs.skopeo;
    };
  in pkgs.runCommand "skopeo-alone-xz" {
    inherit image;
  } ''
    gzip -dc $image | xz -0 -zc - > $out
  '';
  literally-just-busybox = pkgs.dockerTools.buildImage {
    name = "literally-just-busybox";
    contents = pkgs.busybox;
  };
  busybox-with-curl = pkgs.dockerTools.buildImage (literally-just-busybox.buildArgs // {
    name = "busybox-and-curl";
    contents = pkgs.symlinkJoin {
      name = "contents";
      paths = [
        literally-just-busybox.buildArgs.contents
        pkgs.curl
        pkgs.cacert
      ];
    };
    config.Env = [
      "NIX_SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
    ];
  });
}
