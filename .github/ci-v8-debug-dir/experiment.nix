# Fork-only experiment for nodejs/node#67303.
{ tarDir }:
let
  pkgs = import (tarDir + "/tools/nix/pkgs.nix") { };
  plain = (import (tarDir + "/tools/nix/ci-shell.nix") { }).v8Derivation;
  stdenv = pkgs.ccacheStdenv.override {
    extraConfig = ''
      export CCACHE_DIR=/nix/var/cache/v8-debug-dir
      export CCACHE_BASEDIR="$NIX_BUILD_TOP"
      export CCACHE_SLOPPINESS=random_seed
      export CCACHE_UMASK=000
      export CCACHE_MAXSIZE=5G
    '';
  };
  debugFlag = "-fdebug-compilation-dir=.";
  probe = name: stdenv.mkDerivation {
    inherit name;
    dontUnpack = true;
    dontStrip = true;
    NIX_CFLAGS_COMPILE = debugFlag;
    buildPhase = ''
      echo 'int square(int x) { return x * x; }' > probe.cc
      $CXX -O2 -gdwarf-2 -c probe.cc -o probe.o
    '';
    installPhase = "install -Dm644 probe.o -t $out";
  };
in {
  inherit (pkgs) ccache;
  probeA = probe "v8-debug-dir-probe-a";
  probeB = probe "v8-debug-dir-probe-b";
  v8 = (plain.override { inherit stdenv; }).overrideAttrs (old: {
    NIX_CFLAGS_COMPILE = (old.NIX_CFLAGS_COMPILE or "") + " " + debugFlag;
  });
}
