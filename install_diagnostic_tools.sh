#!/bin/bash

# LTFS GUI Diagnostic Tools Installation Script
# Installs optional tools for enhanced tape drive diagnostics

set -e

echo "LTFS GUI Diagnostic Tools Installation"
echo "====================================="
echo

# Detect distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    DISTRO="$ID"
    DISTRO_LIKE="$ID_LIKE"
else
    echo "❌ Cannot detect Linux distribution"
    exit 1
fi

echo "Detected distribution: $PRETTY_NAME"
echo

# Define tools and their packages for different distributions
declare -A DEBIAN_PACKAGES=(
    ["sg3-utils"]="sg3-utils"
    ["tapeinfo"]="tapeinfo"
    ["lsscsi"]="lsscsi"
    ["sysstat"]="sysstat"
)

declare -A RHEL_PACKAGES=(
    ["sg3-utils"]="sg3_utils"
    ["tapeinfo"]="mt-st"
    ["lsscsi"]="lsscsi"
    ["sysstat"]="sysstat"
)

declare -A FEDORA_PACKAGES=(
    ["sg3-utils"]="sg3_utils"
    ["tapeinfo"]="mt-st"
    ["lsscsi"]="lsscsi"
    ["sysstat"]="sysstat"
)

declare -A OPENSUSE_PACKAGES=(
    ["sg3-utils"]="sg3_utils"
    ["tapeinfo"]="mt_st"
    ["lsscsi"]="lsscsi"
    ["sysstat"]="sysstat"
)

declare -A ARCH_PACKAGES=(
    ["sg3-utils"]="sg3_utils"
    ["tapeinfo"]="mt-st"
    ["lsscsi"]="lsscsi"
    ["sysstat"]="sysstat"
)

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to install packages based on distribution
install_packages() {
    local packages=("$@")
    
    case "$DISTRO" in
        ubuntu|debian)
            echo "Installing packages for Debian/Ubuntu..."
            sudo apt update
            sudo apt install -y "${packages[@]}"
            ;;
        rhel|centos|rocky|almalinux)
            echo "Installing packages for RHEL/CentOS..."
            if command_exists dnf; then
                sudo dnf install -y "${packages[@]}"
            elif command_exists yum; then
                sudo yum install -y "${packages[@]}"
            else
                echo "❌ No package manager found (dnf/yum)"
                exit 1
            fi
            ;;
        fedora)
            echo "Installing packages for Fedora..."
            sudo dnf install -y "${packages[@]}"
            ;;
        opensuse*|sles)
            echo "Installing packages for openSUSE/SLES..."
            sudo zypper install -y "${packages[@]}"
            ;;
        arch|manjaro)
            echo "Installing packages for Arch Linux..."
            sudo pacman -S --noconfirm "${packages[@]}"
            ;;
        *)
            if [[ "$DISTRO_LIKE" == *"debian"* ]]; then
                echo "Installing packages for Debian-like distribution..."
                sudo apt update
                sudo apt install -y "${packages[@]}"
            elif [[ "$DISTRO_LIKE" == *"rhel"* ]] || [[ "$DISTRO_LIKE" == *"fedora"* ]]; then
                echo "Installing packages for RHEL-like distribution..."
                if command_exists dnf; then
                    sudo dnf install -y "${packages[@]}"
                elif command_exists yum; then
                    sudo yum install -y "${packages[@]}"
                else
                    echo "❌ No package manager found (dnf/yum)"
                    exit 1
                fi
            else
                echo "❌ Unsupported distribution: $DISTRO"
                echo "Please install these packages manually:"
                printf "  %s\n" "${packages[@]}"
                exit 1
            fi
            ;;
    esac
}

# Get package list based on distribution
get_packages() {
    local -n package_map=$1
    local packages=()
    
    for tool in "${!package_map[@]}"; do
        packages+=("${package_map[$tool]}")
    done
    
    echo "${packages[@]}"
}

# Check current installation status
echo "Checking current tool availability..."
TOOLS=(
    "sg_inq:SCSI inquiry utility"
    "sg_logs:SCSI log page utility"
    "sg_vpd:SCSI VPD utility"
    "tapeinfo:Tape information utility"
    "lsscsi:List SCSI devices"
    "iostat:I/O statistics utility"
)

MISSING_TOOLS=()
AVAILABLE_TOOLS=()

for tool_info in "${TOOLS[@]}"; do
    IFS=':' read -r cmd desc <<< "$tool_info"
    if command_exists "$cmd"; then
        echo "✅ $desc ($cmd)"
        AVAILABLE_TOOLS+=("$cmd")
    else
        echo "❌ $desc ($cmd) - NOT FOUND"
        MISSING_TOOLS+=("$cmd")
    fi
done

echo
echo "Summary: ${#AVAILABLE_TOOLS[@]}/${#TOOLS[@]} tools available"

if [ ${#MISSING_TOOLS[@]} -eq 0 ]; then
    echo "🎉 All diagnostic tools are already installed!"
    exit 0
fi

echo
echo "Missing tools: ${MISSING_TOOLS[*]}"
echo

# Determine packages to install
case "$DISTRO" in
    ubuntu|debian)
        PACKAGES=($(get_packages DEBIAN_PACKAGES))
        ;;
    rhel|centos|rocky|almalinux)
        PACKAGES=($(get_packages RHEL_PACKAGES))
        ;;
    fedora)
        PACKAGES=($(get_packages FEDORA_PACKAGES))
        ;;
    opensuse*|sles)
        PACKAGES=($(get_packages OPENSUSE_PACKAGES))
        ;;
    arch|manjaro)
        PACKAGES=($(get_packages ARCH_PACKAGES))
        ;;
    *)
        if [[ "$DISTRO_LIKE" == *"debian"* ]]; then
            PACKAGES=($(get_packages DEBIAN_PACKAGES))
        elif [[ "$DISTRO_LIKE" == *"rhel"* ]] || [[ "$DISTRO_LIKE" == *"fedora"* ]]; then
            PACKAGES=($(get_packages RHEL_PACKAGES))
        else
            echo "❌ Unsupported distribution for automatic installation"
            echo "Please install these packages manually:"
            echo "  - SCSI utilities (sg3-utils or sg3_utils)"
            echo "  - Tape utilities (tapeinfo or mt-st)"
            echo "  - SCSI listing (lsscsi)"
            echo "  - System statistics (sysstat)"
            exit 1
        fi
        ;;
esac

echo "Packages to install: ${PACKAGES[*]}"
echo

read -p "Proceed with installation? (y/N): " confirm
if [[ ! $confirm =~ ^[Yy] ]]; then
    echo "Installation cancelled."
    exit 0
fi

echo
echo "Installing diagnostic tools..."
install_packages "${PACKAGES[@]}"

echo
echo "Verifying installation..."
NEW_AVAILABLE=()
STILL_MISSING=()

for tool_info in "${TOOLS[@]}"; do
    IFS=':' read -r cmd desc <<< "$tool_info"
    if command_exists "$cmd"; then
        echo "✅ $desc ($cmd)"
        NEW_AVAILABLE+=("$cmd")
    else
        echo "❌ $desc ($cmd) - STILL MISSING"
        STILL_MISSING+=("$cmd")
    fi
done

echo
echo "Installation Summary:"
echo "==================="
echo "✅ Available tools: ${#NEW_AVAILABLE[@]}/${#TOOLS[@]}"

if [ ${#STILL_MISSING[@]} -gt 0 ]; then
    echo "❌ Still missing: ${STILL_MISSING[*]}"
    echo
    echo "Some tools may be in different packages on your distribution."
    echo "The LTFS GUI will work with whatever tools are available."
else
    echo "🎉 All diagnostic tools successfully installed!"
fi

echo
echo "You can now use the full diagnostic functionality in LTFS GUI."
echo "Launch with: ltfs-gui"

