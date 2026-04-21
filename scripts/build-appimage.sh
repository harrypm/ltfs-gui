#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ROOT="${REPO_ROOT}/build/appimage"
PYINSTALLER_ROOT="${BUILD_ROOT}/pyinstaller"
APPDIR="${BUILD_ROOT}/AppDir"
DIST_DIR="${REPO_ROOT}/dist"

APP_NAME="LTFS-Manager"
DESKTOP_ID="ltfs-gui"
BINARY_NAME="ltfs-gui"
ICON_BASENAME="${DESKTOP_ID}.png"

PYTHON_BIN="${PYTHON_BIN:-python3}"
APPIMAGETOOL_BIN="${APPIMAGETOOL_BIN:-}"
APPIMAGETOOL_VERSION="${APPIMAGETOOL_VERSION:-12}"
APPIMAGETOOL_BASE_URL="${APPIMAGETOOL_BASE_URL:-https://github.com/AppImage/AppImageKit/releases/download/${APPIMAGETOOL_VERSION}}"
VENDORED_APPIMAGETOOL_DIR="${REPO_ROOT}/vendor/appimagetool"
APPIMAGETOOL_CHECKSUMS="${VENDORED_APPIMAGETOOL_DIR}/SHA256SUMS"
APPIMAGE_REQUIREMENTS="${REPO_ROOT}/packaging/appimage/requirements.txt"
PIP_VERSION="${PIP_VERSION:-24.3.1}"
SETUPTOOLS_VERSION="${SETUPTOOLS_VERSION:-75.6.0}"
WHEEL_VERSION="${WHEEL_VERSION:-0.45.1}"

python_has_tk() {
  local candidate="$1"
  "${candidate}" - <<'PY' >/dev/null 2>&1
import tkinter
PY
}

expected_appimagetool_sha256() {
  local arch="$1"
  local filename="appimagetool-${arch}.AppImage"
  if [[ ! -f "${APPIMAGETOOL_CHECKSUMS}" ]]; then
    return 1
  fi
  awk -v target="${filename}" '$2 == target {print $1; found=1} END {if (!found) exit 1}' "${APPIMAGETOOL_CHECKSUMS}"
}

verify_sha256() {
  local expected="$1"
  local file="$2"
  local actual

  actual="$(sha256sum "${file}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Checksum mismatch for ${file}" >&2
    echo "Expected: ${expected}" >&2
    echo "Actual:   ${actual}" >&2
    exit 1
  fi
}

copy_fuse_library() {
  local soname="$1"
  local source_path=""
  local destination="${APPDIR}/usr/lib/${soname}"

  if command -v ldconfig >/dev/null 2>&1; then
    source_path="$(ldconfig -p 2>/dev/null | awk -v lib="${soname}" '$1 == lib {print $NF; exit}')"
  fi

  if [[ -z "${source_path}" ]]; then
    for candidate in \
      "/lib/${soname}" \
      "/usr/lib/${soname}" \
      "/lib64/${soname}" \
      "/usr/lib64/${soname}" \
      "/usr/lib/x86_64-linux-gnu/${soname}" \
      "/usr/lib/aarch64-linux-gnu/${soname}"
    do
      if [[ -e "${candidate}" ]]; then
        source_path="${candidate}"
        break
      fi
    done
  fi

  if [[ -z "${source_path}" ]]; then
    return 1
  fi

  cp -L "${source_path}" "${destination}"
  return 0
}

for cmd in "${PYTHON_BIN}" curl sha256sum; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}" >&2
    exit 1
  fi
done
if ! python_has_tk "${PYTHON_BIN}"; then
  if [[ "${PYTHON_BIN}" == "python3" ]] && [[ -x "/usr/bin/python3" ]] && python_has_tk "/usr/bin/python3"; then
    PYTHON_BIN="/usr/bin/python3"
  else
    echo "Python tkinter support is required to package the GUI (missing module: tkinter)." >&2
    echo "Install tkinter for the selected Python interpreter and retry." >&2
    exit 1
  fi
fi
if [[ ! -f "${APPIMAGE_REQUIREMENTS}" ]]; then
  echo "Missing AppImage requirements file: ${APPIMAGE_REQUIREMENTS}" >&2
  exit 1
fi

rm -rf "${BUILD_ROOT}"
mkdir -p "${PYINSTALLER_ROOT}" "${APPDIR}" "${DIST_DIR}"

"${PYTHON_BIN}" -m venv "${BUILD_ROOT}/venv"
# shellcheck disable=SC1091
source "${BUILD_ROOT}/venv/bin/activate"
python -m pip install --upgrade \
  "pip==${PIP_VERSION}" \
  "setuptools==${SETUPTOOLS_VERSION}" \
  "wheel==${WHEEL_VERSION}"
python -m pip install --upgrade --requirement "${APPIMAGE_REQUIREMENTS}"

pushd "${REPO_ROOT}" >/dev/null
pyinstaller \
  --noconfirm \
  --clean \
  --name "${BINARY_NAME}" \
  --onedir \
  --distpath "${PYINSTALLER_ROOT}/dist" \
  --workpath "${PYINSTALLER_ROOT}/build" \
  --specpath "${PYINSTALLER_ROOT}" \
  ltfs_gui.py
popd >/dev/null

mkdir -p \
  "${APPDIR}/usr/bin" \
  "${APPDIR}/usr/lib" \
  "${APPDIR}/usr/share/applications" \
  "${APPDIR}/usr/share/icons/hicolor/scalable/apps"

cp -a "${PYINSTALLER_ROOT}/dist/${BINARY_NAME}/." "${APPDIR}/usr/bin/"
cp "${REPO_ROOT}/packaging/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

sed \
  -e "s|^Exec=.*|Exec=${BINARY_NAME} %U|" \
  -e "s|^Icon=.*|Icon=${DESKTOP_ID}|" \
  "${REPO_ROOT}/ltfs-gui.desktop" > "${APPDIR}/usr/share/applications/${DESKTOP_ID}.desktop"

cp "${REPO_ROOT}/packaging/appimage/${ICON_BASENAME}" \
  "${APPDIR}/usr/share/icons/hicolor/scalable/apps/${ICON_BASENAME}"
cp "${REPO_ROOT}/packaging/appimage/${ICON_BASENAME}" "${APPDIR}/${ICON_BASENAME}"
cp "${REPO_ROOT}/packaging/appimage/${ICON_BASENAME}" "${APPDIR}/usr/bin/${ICON_BASENAME}"
cp "${APPDIR}/usr/share/applications/${DESKTOP_ID}.desktop" "${APPDIR}/${DESKTOP_ID}.desktop"
ln -sf "${ICON_BASENAME}" "${APPDIR}/.DirIcon"
if ! copy_fuse_library "libfuse.so.2"; then
  echo "Required FUSE runtime library not found: libfuse.so.2" >&2
  echo "Install libfuse2 (and libfuse-dev for build environments) before building AppImage." >&2
  exit 1
fi

# Optional secondary FUSE runtime where available.
copy_fuse_library "libfuse3.so.3" || true

RAW_ARCH="${ARCH:-$(uname -m)}"
case "${RAW_ARCH}" in
  x86_64|amd64) APPIMAGE_ARCH="x86_64" ;;
  aarch64|arm64) APPIMAGE_ARCH="aarch64" ;;
  *) APPIMAGE_ARCH="${RAW_ARCH}" ;;
esac

if [[ -z "${APPIMAGETOOL_BIN}" ]]; then
  VENDORED_APPIMAGETOOL="${VENDORED_APPIMAGETOOL_DIR}/appimagetool-${APPIMAGE_ARCH}.AppImage"
  if [[ -x "${VENDORED_APPIMAGETOOL}" ]]; then
    APPIMAGETOOL_BIN="${VENDORED_APPIMAGETOOL}"
  else
    APPIMAGETOOL_BIN="${BUILD_ROOT}/appimagetool-${APPIMAGE_ARCH}.AppImage"
    curl -L --fail \
      "${APPIMAGETOOL_BASE_URL}/appimagetool-${APPIMAGE_ARCH}.AppImage" \
      -o "${APPIMAGETOOL_BIN}"
    chmod +x "${APPIMAGETOOL_BIN}"
  fi
fi

if [[ ! -x "${APPIMAGETOOL_BIN}" ]]; then
  echo "appimagetool binary is not executable: ${APPIMAGETOOL_BIN}" >&2
  exit 1
fi

EXPECTED_APPIMAGETOOL_SHA256="$(expected_appimagetool_sha256 "${APPIMAGE_ARCH}" || true)"
if [[ -n "${EXPECTED_APPIMAGETOOL_SHA256}" ]]; then
  verify_sha256 "${EXPECTED_APPIMAGETOOL_SHA256}" "${APPIMAGETOOL_BIN}"
else
  echo "Warning: No pinned appimagetool checksum configured for architecture ${APPIMAGE_ARCH}; skipping checksum verification." >&2
fi
OUTPUT_APPIMAGE="${DIST_DIR}/${APP_NAME}-${APPIMAGE_ARCH}.AppImage"
ARCH="${APPIMAGE_ARCH}" "${APPIMAGETOOL_BIN}" "${APPDIR}" "${OUTPUT_APPIMAGE}"
chmod +x "${OUTPUT_APPIMAGE}"

echo "Created ${OUTPUT_APPIMAGE}"
