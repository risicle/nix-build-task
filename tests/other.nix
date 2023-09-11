{
  pkgs ? import (import ../nix/sources.nix).nixpkgs {}
  , readmeExt ? ".md"
  , includeTarball ? true
  , someArg ? "default"
  , ...
}:
let
  mkNonDeterministicDrv = arg: runTimeDep: buildTimeDep: pkgs.runCommand "deliberately-non-deterministic" {
    inherit arg runTimeDep buildTimeDep;
  } ''
    mkdir -p $out
    echo $arg > $out/arg
    echo $RANDOM > $out/value
    echo contained-${arg}-contained > $out/arg-contained
    [ -n "$runTimeDep" ] && ln -s $runTimeDep $out/run-time-dep
    [ -n "$buildTimeDep" ] && cp -rL $buildTimeDep $out/build-time-dep
    echo Building something slightly random: arg=$arg value=$(cat $out/value) runTimeDep=$runTimeDep buildTimeDep=$buildTimeDep
  '';
in rec {
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
  bash = pkgs.bash;
  deliberatelyNonDeterministicBTD = mkNonDeterministicDrv "${someArg}-btd" "" "";
  deliberatelyNonDeterministicRTD = mkNonDeterministicDrv "${someArg}-rtd" "" "";
  deliberatelyNonDeterministic = mkNonDeterministicDrv someArg deliberatelyNonDeterministicRTD deliberatelyNonDeterministicBTD;
  multiOut = pkgs.runCommand "multi-out-foo" {
    outputs = [ "out" "foo" "bar" "baz" ];
  } ''
    mkdir -p $foo
    touch $bar
    mkdir -p $baz
    mkdir -p $out
  '';
}
