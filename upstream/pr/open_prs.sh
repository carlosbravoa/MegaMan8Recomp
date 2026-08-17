#!/usr/bin/env bash
# open_prs.sh — push the three framework fixes and open PRs against
# mstan/psxrecomp. NOT run automatically: this posts publicly, under your
# GitHub account, to someone else's repository.
#
# Read upstream/pr/000*-body.md first. In particular PR 3 is a large refactor of
# runtime/src/autocompile.c that could NOT be built on Windows here — its body
# says so explicitly, and you may prefer to hold it until CI or a Windows box
# has confirmed the Windows arms compile.
#
# Usage:
#   bash upstream/pr/open_prs.sh --dry-run     # print what it would do
#   bash upstream/pr/open_prs.sh 1 2           # only patches 1 and 2
#   bash upstream/pr/open_prs.sh               # all three
set -euo pipefail

GH=${GH:-$HOME/tools/gh}
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
fw=$root/psxrecomp
upstream_repo=mstan/psxrecomp
dry=0
declare -a want=()

for a in "$@"; do
    case "$a" in
        --dry-run) dry=1 ;;
        1|2|3) want+=("$a") ;;
        *) echo "unknown argument: $a" >&2; exit 2 ;;
    esac
done
[ ${#want[@]} -gt 0 ] || want=(1 2 3)

titles=(
    ""
    "gpu: depth24 upload span must intersect the scanout band"
    "widescreen: bg2d startcol_site should accept an unmasked sra"
    "autocompile: portable POSIX spawner and one shared publication pipeline"
)
branches=(
    ""
    "fix/depth24-span-scanout-band"
    "fix/bg2d-startcol-unmasked-sra"
    "feat/autocompile-posix-portable"
)
# Files each patch owns, so the commits stay separable from a working tree that
# has all three applied at once.
paths_1="runtime/src/gpu.c runtime/src/debug_server.c"
paths_2="recompiler/src/code_generator.cpp"
paths_3="runtime/src/autocompile.c runtime/CMakeLists.txt runtime/tests/test_autocompile_publication.c runtime/tests/test_autocompile_degraded.c"

run() { if [ "$dry" = 1 ]; then echo "  + $*"; else "$@"; fi; }

# `origin` is mstan/psxrecomp, which you cannot push to. Branches go to your own
# fork and the PRs are opened cross-repo, so --head must be owner:branch.
me=$("$GH" api user --jq .login 2>/dev/null || echo "")
[ -n "$me" ] || { echo "gh is not authenticated ($GH)" >&2; exit 1; }
fork_remote=fork
if ! git -C "$fw" remote get-url "$fork_remote" >/dev/null 2>&1; then
    echo "creating/attaching your fork of $upstream_repo as remote '$fork_remote'"
    run "$GH" repo fork "$upstream_repo" --clone=false --remote=false
    run git -C "$fw" remote add "$fork_remote" "git@github.com:$me/psxrecomp.git"
fi

base=$(git -C "$fw" rev-parse HEAD)
echo "framework base: $base"
echo "pushing to:     $me/psxrecomp (remote '$fork_remote')"

for n in "${want[@]}"; do
    br=${branches[$n]}
    ti=${titles[$n]}
    body=$root/upstream/pr/000$n-body.md
    eval "files=\$paths_$n"
    echo
    echo "=== PR $n: $ti"
    echo "    branch $br"
    echo "    files  $files"
    [ -f "$body" ] || { echo "missing body: $body" >&2; exit 1; }

    run git -C "$fw" switch -c "$br" "$base"
    # shellcheck disable=SC2086
    run git -C "$fw" add -- $files
    run git -C "$fw" commit -m "$ti"
    run git -C "$fw" push -u "$fork_remote" "$br"
    run "$GH" pr create --repo "$upstream_repo" \
        --head "$me:$br" --base master --title "$ti" --body-file "$body"
done

# Each `switch -c <br> <base>` above rewinds the files committed by the previous
# iteration back to base content. Return to the detached base and re-apply every
# patch, so the working tree ends exactly as it started: all three fixes live,
# which is what the local build expects.
echo
echo "restoring the working tree (detached at base, all patches re-applied)"
run git -C "$fw" switch --detach "$base"
for pf in "$root"/upstream/000*.patch; do
    if [ "$dry" = 1 ]; then
        echo "  + git -C $fw apply $pf"
    elif git -C "$fw" apply --check "$pf" 2>/dev/null; then
        git -C "$fw" apply "$pf"
    fi
done
if [ "$dry" = 0 ]; then
    echo "re-applied; rebuild before playing:"
    echo "  bash psxrecomp/tools/ci/build_emitters.sh"
    echo "  cmake --build build-release --target psx-runtime -j\"$(nproc)\""
fi

echo
echo "Done. The commits live on their branches; the working tree is back at"
echo "$base with all three fixes applied."
