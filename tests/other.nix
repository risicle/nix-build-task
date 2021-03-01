{
  pkgs ? import (import ../nix/sources.nix).nixpkgs {}
  , readmeExt ? ".md"
  , includeTarball ? true
  , ...
}:

rec {
  linux_1_0 = pkgs.fetchurl {
    url = "https://kernel.org/pub/linux/kernel/v1.0/linux-1.0.tar.gz";
    sha256 = "00hqn0mdf3097f69zib8q6la8i8f1qaf6hxp7r46mnx3d7mc6k01";
  };
  linux-dir = pkgs.linkFarm "linux-dir" (
    [
      {name = "README${readmeExt}"; path = pkgs.writeText "README" "Not a lot";}
      {name = "linux_1_0"; path = pkgs.runCommand "linux_1_0" {} ''
        mkdir $out
        tar -C $out -zxf ${linux_1_0}
      '';}
    ] ++ pkgs.lib.optional includeTarball {name = "linux_1_0.tar.gz"; path = linux_1_0;}
  );
  skopeo = pkgs.skopeo;
  deliberatelyNonDeterministic = pkgs.runCommand "deliberately-non-deterministic" {} ''
    mkdir -p $out
    touch $out/$RANDOM
  '';
}
