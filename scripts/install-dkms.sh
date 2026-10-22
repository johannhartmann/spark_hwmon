#!/usr/bin/env bash
# Build before replacing the running kernel's module; preserve other kernels.
set -euo pipefail
[[ $EUID == 0 ]] || { echo "Run with sudo: $0" >&2; exit 1; }
repo=$(cd -- "$(dirname -- "$0")/.." && pwd)
version=$(sed -n 's/^PACKAGE_VERSION="\([^"]*\)"$/\1/p' "$repo/dkms.conf")
[[ $version =~ ^[0-9A-Za-z._+-]+$ ]]
release=$(uname -r)
source_dir=/usr/src/spbm-$version
files=(spbm.c n1x-acpi.h Makefile dkms.conf)
if [[ -e $source_dir ]]; then
  for file in "${files[@]}"; do
    cmp -s "$repo/$file" "$source_dir/$file" || {
      echo "Source changed without a version bump: $source_dir/$file" >&2; exit 1;
    }
  done
else
  install -d "$source_dir"
  for file in "${files[@]}"; do install -m644 "$repo/$file" "$source_dir/$file"; done
fi
if [[ ! -e /var/lib/dkms/spbm/$version/source ]]; then
  dkms add -m spbm -v "$version"
fi
dkms build -m spbm -v "$version" -k "$release"
old=$(dkms status -m spbm -k "$release" | sed -n 's|^spbm/\([^,]*\),.*: installed$|\1|p')
[[ $old != *$'\n'* ]] || { echo 'Multiple installed versions; refusing replacement.' >&2; exit 1; }
was_loaded=false
[[ ! -d /sys/module/spbm ]] || was_loaded=true
changed=false
rollback() {
  status=$?
  trap - EXIT
  if ((status != 0)) && $changed; then
    modprobe -r spbm || true
    dkms uninstall -m spbm -v "$version" -k "$release" || true
    if [[ -n $old ]]; then
      dkms install -m spbm -v "$old" -k "$release"
      if $was_loaded; then modprobe spbm; fi
      echo "Restored spbm/$old for $release" >&2
    fi
  fi
  exit "$status"
}
trap rollback EXIT
# A busy module must stop the upgrade before any installed module is removed.
if $was_loaded; then modprobe -r spbm; fi
changed=true
if [[ -n $old && $old != "$version" ]]; then
  dkms uninstall -m spbm -v "$old" -k "$release"
fi
dkms install --force -m spbm -v "$version" -k "$release"
modprobe spbm
[[ $(cat /sys/module/spbm/version) == "$version" ]]
printf 'Loaded spbm/%s; other kernels preserved.\n' "$version"
