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

PYTHON_BIN="${PYTHON_BIN:-python3}"
APPIMAGETOOL_BIN="${APPIMAGETOOL_BIN:-}"

for cmd in "${PYTHON_BIN}" curl; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found: ${cmd}" >&2
    exit 1
  fi
done

if ! "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import tkinter
PY
then
  echo "Python tkinter support is required to package the GUI (missing module: tkinter)." >&2
  echo "Install tkinter for the selected Python interpreter and retry." >&2
  exit 1
fi

rm -rf "${BUILD_ROOT}"
mkdir -p "${PYINSTALLER_ROOT}" "${APPDIR}" "${DIST_DIR}"

"${PYTHON_BIN}" -m venv "${BUILD_ROOT}/venv"
# shellcheck disable=SC1091
source "${BUILD_ROOT}/venv/bin/activate"

pip install --upgrade pip
pip install pyinstaller

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
  "${APPDIR}/usr/share/applications" \
  "${APPDIR}/usr/share/icons/hicolor/scalable/apps"

cp -a "${PYINSTALLER_ROOT}/dist/${BINARY_NAME}/." "${APPDIR}/usr/bin/"
cp "${REPO_ROOT}/packaging/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

sed \
  -e "s|^Exec=.*|Exec=${BINARY_NAME} %U|" \
  -e "s|^Icon=.*|Icon=${DESKTOP_ID}|" \
  "${REPO_ROOT}/ltfs-gui.desktop" > "${APPDIR}/usr/share/applications/${DESKTOP_ID}.desktop"

cp "${REPO_ROOT}/packaging/appimage/${DESKTOP_ID}.svg" \
  "${APPDIR}/usr/share/icons/hicolor/scalable/apps/${DESKTOP_ID}.svg"
cp "${REPO_ROOT}/packaging/appimage/${DESKTOP_ID}.svg" "${APPDIR}/${DESKTOP_ID}.svg"
cp "${APPDIR}/usr/share/applications/${DESKTOP_ID}.desktop" "${APPDIR}/${DESKTOP_ID}.desktop"
ln -sf "${DESKTOP_ID}.svg" "${APPDIR}/.DirIcon"

RAW_ARCH="${ARCH:-$(uname -m)}"
case "${RAW_ARCH}" in
  x86_64|amd64) APPIMAGE_ARCH="x86_64" ;;
  aarch64|arm64) APPIMAGE_ARCH="aarch64" ;;
  *) APPIMAGE_ARCH="${RAW_ARCH}" ;;
esac

if [[ -z "${APPIMAGETOOL_BIN}" ]]; then
  if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL_BIN="appimagetool"
  else
    APPIMAGETOOL_BIN="${BUILD_ROOT}/appimagetool-${APPIMAGE_ARCH}.AppImage"
    curl -L --fail \
      "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${APPIMAGE_ARCH}.AppImage" \
      -o "${APPIMAGETOOL_BIN}"
    chmod +x "${APPIMAGETOOL_BIN}"
  fi
fi

OUTPUT_APPIMAGE="${DIST_DIR}/${APP_NAME}-${APPIMAGE_ARCH}.AppImage"
ARCH="${APPIMAGE_ARCH}" "${APPIMAGETOOL_BIN}" "${APPDIR}" "${OUTPUT_APPIMAGE}"
chmod +x "${OUTPUT_APPIMAGE}"

echo "Created ${OUTPUT_APPIMAGE}"
