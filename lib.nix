{ pkgs, ... }:

rec {
  writeImageDigestFile = imageTarball: pkgs.runCommand "digest" {
    inherit imageTarball;
    buildInputs = [ pkgs.skopeo pkgs.jq ];
  } ''
    skopeo inspect "docker-archive:$imageTarball" --raw | jq -r '.config.digest' > $out
  '';
  concourseStyleImageOutput = imageTarball: let
    imageTar = pkgs.runCommand "image.tar" {
      inherit imageTarball;
      buildInputs = [ pkgs.pigz ];
    } ''
      pigz -dc "$imageTarball" > $out
    '';
  in pkgs.linkFarm "output" [
    { name = "image.tar"; path = imageTar;}
    { name = "digest"; path = writeImageDigestFile imageTar;}
  ];
}
