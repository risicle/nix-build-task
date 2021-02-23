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
    sha256 = "1bgva9np37zmijgbk0lvw7ywfv7zkxqsi1dm7m4i6n5pj8l51afg";
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
  literally-just-bash = pkgs.dockerTools.buildImage {
    name = "literally-just-bash";

    contents = pkgs.bash;
  };
}
