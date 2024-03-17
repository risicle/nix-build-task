{ pkgs ? import (import ./nix/sources.nix).nixpkgs {}
, nix ? (import ./nix/sources.nix).nix
, ...
}:

rec {
  inherit (pkgs) niv;
  image = ((import (nix + "/docker.nix")) {
    inherit pkgs;
    bundleNixpkgs = false;
    maxLayers = 95;
  }).override (origArgs: {
    name = "nix-build-task";
    tag = "latest";

    contents = origArgs.contents ++ [(
      pkgs.runCommand "nix-build-task-build" {
        buildInputs = [ pkgs.python3 pkgs.makeWrapper ];
        wrappedPath = pkgs.lib.makeBinPath (with pkgs; [
          cachix
          gnutar
          gzip
          pkgs.nix
          umoci
          skopeo
          xz
        ]);
      } ''
        mkdir -p $out/bin
        cp ${./build.py} $out/bin/build
        wrapProgram $out/bin/build \
          --set PATH $wrappedPath
        patchShebangs $out/bin
      ''
    )];

    config = origArgs.config // {
      Cmd = [ "/bin/build" ];
    };
  });
  busyboxGitImage = pkgs.dockerTools.buildLayeredImage {
    name = "nix-build-task-busybox-git";
    contents = with pkgs; [
      bash
      busybox
      git
    ];
  };
  bumpSources = pkgs.writeScript "bump-sources" ''
    #!${pkgs.bash}/bin/bash
    set -e

    ${pkgs.niv}/bin/niv update nix
    ${pkgs.niv}/bin/niv update nixpkgs
  '';
  bumpMinorVersion = pkgs.writeScript "bump-minor-version" ''
    #!${pkgs.bash}/bin/bash
    set -e

    ${pkgs.semver-tool}/bin/semver bump patch "$(cat ./VERSION)" > ./VERSION
  '';
  bumpSourcesImage = pkgs.dockerTools.buildLayeredImage {
    name = "nix-build-task-bump-sources";
    contents = with pkgs; [
      bash
      cacert
      git
      nix
      busybox
      (linkFarm "bump-sources-bin" [
        {name = "bin/bump-sources"; path = bumpSources;}
        {name = "bin/bump-minor-version"; path = bumpMinorVersion;}
      ])
    ];
    config.Env = let
      crtFile = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    in [
      "GIT_SSL_CAINFO=${crtFile}"
      "NIX_SSL_CERT_FILE=${crtFile}"
    ];
  };
}
