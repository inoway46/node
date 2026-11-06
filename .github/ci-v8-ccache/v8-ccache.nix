# Fork-only experiment (inoway46/node); not for upstream.
# Builds the CI V8 derivation (tools/nix/ci-shell.nix) with ccache.
{
  tarDir,
  ccacheDir ? "/nix/var/cache/ccache",
}:
let
  pkgs = import (tarDir + "/tools/nix/pkgs.nix") { };

  # Exactly what test-shared.yml builds and looks up in nodejs.cachix.org.
  plain = (import (tarDir + "/tools/nix/ci-shell.nix") { }).v8Derivation;

  ccacheStdenv = pkgs.ccacheStdenv.override {
    extraConfig = ''
      export CCACHE_DIR=${ccacheDir}
      export CCACHE_BASEDIR="$NIX_BUILD_TOP"
      export CCACHE_COMPRESS=1
      export CCACHE_UMASK=000
      export CCACHE_MAXSIZE=5G
      # cc-wrapper adds -frandom-seed=<hash of $out>, which differs for every
      # derivation; without this sloppiness nothing would ever hit.
      export CCACHE_SLOPPINESS=random_seed
      if [ ! -w "$CCACHE_DIR" ]; then
        echo "ccache: '$CCACHE_DIR' is not writable from the build sandbox" >&2
        exit 1
      fi
    '';
  };

  # Tiny derivation to check the mechanics (sandbox path, permissions,
  # CCACHE_BASEDIR across different build dirs) before the long V8 build.
  probe =
    name:
    ccacheStdenv.mkDerivation {
      inherit name;
      dontUnpack = true;
      buildPhase = ''
        mkdir -p inc
        echo '#define PROBE_VALUE 42' > inc/probe.h
        printf '#include "probe.h"\nint probe() { return PROBE_VALUE; }\n' > probe.cc
        # ccache does not use files modified after the compilation started.
        sleep 2
        echo "NIX_BUILD_TOP=$NIX_BUILD_TOP"
        $CXX -O2 -I"$PWD/inc" -c probe.cc -o probe.o
      '';
      installPhase = ''
        install -Dm644 probe.o -t "$out"
      '';
    };
in
{
  inherit plain;
  ccache = plain.override { stdenv = ccacheStdenv; };
  ccacheBin = pkgs.ccache;
  probeA = probe "ccache-probe-a";
  probeB = probe "ccache-probe-b";
}
