#!/bin/bash
# Build wpcap.dll (32-bit) with MinGW inside a throwaway Debian container.
# Output: wpcap.dll next to this script.  Needs docker; no host toolchain required.
set -e
cd "$(dirname "$0")"
docker run --rm -v "$PWD":/w -w /w debian:bookworm-slim sh -c \
  "apt-get update -qq >/dev/null && apt-get install -y -qq gcc-mingw-w64-i686 >/dev/null 2>&1 && \
   i686-w64-mingw32-gcc -shared -O2 -static-libgcc -o wpcap.dll wpcap_shim.c -Wl,--kill-at && \
   i686-w64-mingw32-gcc -O2 -static-libgcc -o shimtest.exe shimtest.c && chown $(id -u):$(id -g) wpcap.dll shimtest.exe"
ls -la wpcap.dll shimtest.exe
