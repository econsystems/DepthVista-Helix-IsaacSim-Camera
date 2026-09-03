#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# e-con DepthVista Helix iToF — Isaac Sim installer (Linux)
#
# Verifies the package, locates Isaac Sim, and registers the econ.itof.menu extension
# so the cameras appear under Create -> Sensors -> Camera and Depth Sensors -> e-con on
# every launch. Pure Python — nothing to compile.
#
# Usage:
#   ./build.sh                         # register the extension with Isaac Sim
#   ISAACSIM_PATH=… ./build.sh         # skip Isaac Sim auto-detection
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Configuration (override via env) ──────────────────────────────────────────
# Two extensions ship together: econ.itof.menu (camera asset / Create menu) and
# econ.itof.ros (ROS 2 publish via baked variant + web viewer + GT viewer + test rig).
EXT_NAMES="${EXT_NAMES:-econ.itof.menu econ.itof.ros}"

# The extension is installed from this package folder — the one holding this script.
INSTALL_DIR="${INSTALL_DIR:-${SCRIPT_DIR}}"

# ── Helpers ───────────────────────────────────────────────────────────────────
info()  { printf '[INFO] %s\n'  "$*"; }
err()   { printf '[ERROR] %s\n' "$*" >&2; }

# ── 1. Sanity-check the extension is present (do NOT build anything) ──────────
for _n in ${EXT_NAMES}; do
    if [ ! -d "${INSTALL_DIR}/exts/${_n}" ]; then
        err "Extension not found at ${INSTALL_DIR}/exts/${_n}."
        err "This package must contain exts/${_n}/ (config/extension.toml + python)."
        exit 1
    fi
    info "Found extension: ${INSTALL_DIR}/exts/${_n}"
done

# ── 2. Locate the Isaac Sim install (holds isaac-sim.sh) ──────────────────────
# Detection order: $ISAACSIM_PATH/$ISAAC_SIM_PATH env -> common locations -> search $HOME ->
# ask the user.  No path is hard-coded to one machine.
ISAACSIM_PATH="${ISAACSIM_PATH:-${ISAAC_SIM_PATH:-}}"
if [ -z "${ISAACSIM_PATH}" ]; then
    for cand in \
        "${HOME}"/.local/share/ov/pkg/isaac-sim-* \
        "${HOME}"/.local/share/ov/pkg/isaac_sim-* \
        "${HOME}/isaacsim" "${HOME}/isaac-sim" \
        "${HOME}"/[Dd]ownloads/isaacsim "${HOME}"/[Dd]ownloads/isaac-sim* \
        /opt/isaacsim /opt/isaac-sim ; do
        if [ -x "${cand}/isaac-sim.sh" ]; then ISAACSIM_PATH="${cand}"; break; fi
    done
fi
if [ -z "${ISAACSIM_PATH}" ]; then
    info "Searching for isaac-sim.sh under ${HOME} …"
    # Prune Trash/.cache (a trashed Isaac copy must not be picked). -print -quit stops at
    # the first real match without a pipe (`| head` would SIGPIPE and trip pipefail);
    # `|| true` guards the no-match case.
    found="$(find "${HOME}" -maxdepth 7 -type d \( -name Trash -o -name .cache \) -prune \
                 -o -type f -name isaac-sim.sh -print -quit 2>/dev/null || true)"
    [ -n "${found}" ] && ISAACSIM_PATH="$(dirname "${found}")"
fi
# Still nothing -> ask the user (interactive only).
while [ -z "${ISAACSIM_PATH}" ] || [ ! -x "${ISAACSIM_PATH}/isaac-sim.sh" ]; do
    if [ ! -t 0 ]; then
        err "Isaac Sim not found. Re-run with: ISAACSIM_PATH=/path/to/isaacsim ./build.sh"
        exit 1
    fi
    printf "Enter the Isaac Sim folder (contains isaac-sim.sh), or blank to abort: "
    read -r ISAACSIM_PATH
    [ -z "${ISAACSIM_PATH}" ] && { err "Aborted — no Isaac Sim path given."; exit 1; }
    ISAACSIM_PATH="${ISAACSIM_PATH/#\~/$HOME}"
    [ -x "${ISAACSIM_PATH}/isaac-sim.sh" ] || err "No isaac-sim.sh in '${ISAACSIM_PATH}' — try again."
done
info "Using Isaac Sim at: ${ISAACSIM_PATH}"

# ── 3. Register so it auto-loads on every normal launch ──────────────────────
#   (a) COPY the self-contained extension (Python + USD assets) into <isaac>/extsUser
#       (already on the search path).  A copy — not a symlink — so the extension keeps
#       working after this package folder is moved or deleted; otherwise a dangling link leaves an
#       unsatisfiable .kit dependency and Isaac Sim refuses to start.  (build.bat does the
#       same with robocopy.)
#   (b) add it to the Full app's .kit [dependencies]  (read fresh each launch, never rewritten;
#       the persistent user config is unreliable on Isaac Sim 5.1).
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found — needed to register the extensions. Install python3 and re-run."
    exit 1
fi

EXTSUSER="${ISAACSIM_PATH}/extsUser"
mkdir -p "${EXTSUSER}"
for _n in ${EXT_NAMES}; do
    _dir="${INSTALL_DIR}/exts/${_n}"
    # econ.itof.ros is fully self-contained (publishing = enabling the baked ROS
    # variant); the repo ros2/ script is only an OFFLINE graph generator, not bundled.
    rm -rf "${EXTSUSER:?}/${_n}"
    cp -r "${_dir}" "${EXTSUSER}/${_n}"
    info "Installed ${EXTSUSER}/${_n}"
    python3 "${INSTALL_DIR}/scripts/patch_kit.py" "${ISAACSIM_PATH}/apps" "${_n}" \
        || { err "Could not patch the Isaac Sim .kit files for ${_n}."; exit 1; }
done

# ── 4. Done ───────────────────────────────────────────────────────────────────
cat <<EOF

[SUCCESS] e-con DepthVista Helix installed (auto-loads on every launch).

  If Isaac Sim is open, fully close and reopen it. Launch normally — no special command.
  Then: Create -> Sensors -> Camera and Depth Sensors -> e-con -> DepthVista Helix iToF

  Uninstall (reverts everything): ./uninstall.sh
EOF
