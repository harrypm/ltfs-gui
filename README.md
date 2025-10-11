![](https://img.shields.io/github/issues/lineartapefilesystem/ltfs.svg)
![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-centos8.yml/badge.svg)
[![BSD License](http://img.shields.io/badge/license-BSD-blue.svg?style=flat)](LICENSE)

# About this branch

This is the `master` branch of the LTFS project. At this time, this branch is used for version 2.5 development. So it wouldn't be stable a little. Please consider to follow the tree on `v2.4-stable` branch if you want to use stable codes.

# What is the Linear Tape File System (LTFS)

The Linear Tape File System (LTFS) is a filesystem to mount a LTFS formatted tape in a tape drive. Once LTFS mounts a LTFS formatted tape as filesystem, user can access to the tape via filesystem API.

Objective of this project is being the reference implementation of the LTFS format Specifications in [SNIA](https://www.snia.org/tech_activities/standards/curr_standards/ltfs).

At this time, the target of this project to meet is the [LTFS format specifications 2.5](https://www.snia.org/sites/default/files/technical_work/LTFS/LTFS_Format_v2.5_Technical_Position.pdf).

## Supported Tape Drives

  | Vendor  | Drive Type              | Minimum F/W Level |
  |:-------:|:-----------------------:|:-----------------:|
  | IBM     | LTO5                    | B170              |
  | IBM     | LTO6                    | None              |
  | IBM     | LTO7                    | None              |
  | IBM     | LTO8                    | HB81              |
  | IBM     | LTO9                    | None              |
  | IBM     | TS1140                  | 3694              |
  | IBM     | TS1150                  | None              |
  | IBM     | TS1155                  | None              |
  | IBM     | TS1160                  | None              |
  | HP      | LTO5                    | T.B.D.            |
  | HP      | LTO6                    | T.B.D.            |
  | HP      | LTO7                    | T.B.D.            |
  | HP      | LTO8                    | T.B.D.            |
  | HP      | LTO9                    | T.B.D.            |
  | Quantum | LTO5 (Only Half Height) | T.B.D.            |
  | Quantum | LTO6 (Only Half Height) | T.B.D.            |
  | Quantum | LTO7 (Only Half Height) | T.B.D.            |
  | Quantum | LTO8 (Only Half Height) | T.B.D.            |
  | Quantum | LTO9 (Only Half Height) | T.B.D.            |

**Note**: Quantum LTO-5 drives require specific block size settings for optimal compatibility. See [Quantum LTO-5 Compatibility Notes](QUANTUM_LTO5_COMPATIBILITY.md) for details.

## LTFS Format Specifications

LTFS Format Specification is specified data placement, shape of index and names of extended attributes for LTFS. This specification is defined in [SNIA](https://www.snia.org/tech_activities/standards/curr_standards/ltfs) first and then it is forwarded to [ISO](https://www.iso.org/home.html) as ISO/IEC 20919 from version 2.2.

The table below show status of the LTFS format Specification

  | Version | Status of SNIA                                                                                                        | Status of ISO                                                        |
  |:-------:|:---------------------------------------------------------------------------------------------------------------------:|:--------------------------------------------------------------------:|
  | 2.2     | [Published](http://snia.org/sites/default/files/LTFS_Format_2.2.0_Technical_Position.pdf)                             | [Published as `20919:2016`](https://www.iso.org/standard/69458.html) |
  | 2.3.1   | [Published](https://www.snia.org/sites/default/files/technical_work/LTFS/LTFS_Format_2.3.1_TechPosition.PDF)          | -                                                                    |
  | 2.4     | [Published](https://www.snia.org/sites/default/files/technical_work/LTFS/LTFS_Format_2.4.0_TechPosition.pdf)          | -                                                                    |
  | 2.5.1   | [Published](https://www.snia.org/sites/default/files/technical-work/ltfs/release/SNIA-LTFS-Format-2-5-1-Standard.pdf) | [Published as `20919:2021`](https://www.iso.org/standard/80598.html) |

# How to use the LTFS (Quick start)

This section is for a person who already has a machine with the LTFS installed. Instructions on how to use the LTFS is also available on [Wiki](https://github.com/LinearTapeFileSystem/ltfs/wiki).

## Step1: List tape drives

`# ltfs -o device_list`

The output is as follows. You have 3 drives in this example and you can use "Device Name" field, like `/dev/sg43` in this case, as the argument of ltfs command to mount the tape drive.

```
50c4 LTFS14000I LTFS starting, LTFS version 2.4.0.0 (10022), log level 2.
50c4 LTFS14058I LTFS Format Specification version 2.4.0.
50c4 LTFS14104I Launched by "/home/piste/ltfsoss/bin/ltfs -o device_list".
50c4 LTFS14105I This binary is built for Linux (x86_64).
50c4 LTFS14106I GCC version is 4.8.5 20150623 (Red Hat 4.8.5-11).
50c4 LTFS17087I Kernel version: Linux version 3.10.0-514.10.2.el7.x86_64 (mockbuild@x86-039.build.eng.bos.redhat.com) (gcc version 4.8.5 20150623 (Red Hat 4.8.5-11) (GCC) ) #1 SMP Mon Feb 20 02:37:52 EST 2017 i386.
50c4 LTFS17089I Distribution: NAME="Red Hat Enterprise Linux Server".
50c4 LTFS17089I Distribution: Red Hat Enterprise Linux Server release 7.3 (Maipo).
50c4 LTFS17089I Distribution: Red Hat Enterprise Linux Server release 7.3 (Maipo).
50c4 LTFS17085I Plugin: Loading "sg" tape backend.
Tape Device list:.
Device Name = /dev/sg43, Vender ID = IBM    , Product ID = ULTRIUM-TD5    , Serial Number = 9A700L0077, Product Name = [ULTRIUM-TD5] .
Device Name = /dev/sg38, Vender ID = IBM    , Product ID = ULT3580-TD6    , Serial Number = 00013B0119, Product Name = [ULT3580-TD6] .
Device Name = /dev/sg37, Vender ID = IBM    , Product ID = ULT3580-TD7    , Serial Number = 00078D00C2, Product Name = [ULT3580-TD7] .
```

## Step2: Format a tape

As described in the LTFS format specifications, LTFS uses the partition feature of the tape drive. This means you can't use a tape just after you purchase a tape. You need format the tape before using it on LTFS.

To format a tape, you can use `mkltfs` command like

`# mkltfs -d 9A700L0077`

In this case, `mkltfs` tries to format a tape in the tape drive `9A700L0077`. You can use the device name `/dev/sg43` instead.

## Step3: Mount a tape through a tape drive

After you prepared a formatted tape, you can mount it through a tape drive like

`# ltfs -o devname=9A700L0077 /ltfs`

In this command, the ltfs command will try to mount the tape in the tape drive `9A700L0077` to `/ltfs` directory. Of course, you can use a device name `/dev/sg43` instead.

If the mount process is successfully done, you can access to the LTFS tape through `/ltfs` directory.

You must not touch any `st` devices while ltfs is mounting a tape.

## Step4: Unmount the tape drive

You can use following command when you want to unmount the tape. The ltfs command try to write the current meta-data to the tape and close the tape cleanly.

`# umount /ltfs`

One thing you need to pay attention to here is, that the unmount command continues to work in the background after it returns. It just initiates a trigger to notify the the ltfs command of the unmount request. Actual unmount is completed when the ltfs command is finished.

## The `ltfs_ordered_copy` utility

The [`ltfs_ordered_copy`](https://github.com/LinearTapeFileSystem/ltfs/wiki/ltfs_ordered_copy) is a program to copy files from source to destination with LTFS  order  optimization.

It is written in python and it can work with both python2 and python3 (Python 2.7 or later is strongly recommended). You need to install the `pyxattr` module for both python2 and python3.

# Building the LTFS from this GitHub project

These instructions will get a copy of the project up and running on your local machine for development and testing purposes.

## Prerequisites for build

### System Requirements

- Linux kernel 2.6 or later with FUSE support
- GCC 4.8 or later (or Clang)
- Python 3.6+ (for GUI and utilities)
- Tape drive with SCSI Generic (sg) support

### Required Dependencies

Before building LTFS, you need to install the following dependencies:

#### Ubuntu/Debian/Linux Mint Systems

```bash
# Update package list
sudo apt update

# Install build tools
sudo apt install build-essential autotools-dev automake libtool pkg-config

# Install core dependencies
sudo apt install libfuse-dev libxml2-dev uuid-dev libicu-dev

# Install ICU development tools
sudo apt install icu-devtools libicu-dev

# Install additional required libraries
sudo apt install libpthread-stubs0-dev

# Install SNMP support (optional but recommended)
sudo apt install libsnmp-dev

# Install Python dependencies for GUI
sudo apt install python3 python3-tk

# For Ubuntu 20.04/22.04 and Debian 10/11 - fix missing icu-config
sudo apt install libicu-dev
# If icu-config is still missing, create a dummy:
if ! command -v icu-config &> /dev/null; then
    echo '#!/bin/bash' | sudo tee /usr/local/bin/icu-config
    echo 'pkg-config "$@" icu-i18n icu-uc icu-io' | sudo tee -a /usr/local/bin/icu-config
    sudo chmod +x /usr/local/bin/icu-config
fi
```

#### RHEL/CentOS/Rocky Linux/Fedora Systems

```bash
# For RHEL 8/CentOS 8/Rocky Linux
sudo dnf groupinstall "Development Tools"
sudo dnf install autoconf automake libtool pkgconfig
sudo dnf install fuse-devel libxml2-devel libuuid-devel libicu-devel
sudo dnf install net-snmp-devel python3 python3-tkinter

# For CentOS 7 (older)
sudo yum groupinstall "Development Tools"
sudo yum install autoconf automake libtool pkgconfig
sudo yum install fuse-devel libxml2-devel libuuid-devel libicu-devel
sudo yum install net-snmp-devel python3 python3-tkinter

# For Fedora (latest)
sudo dnf groupinstall "Development Tools" "Development Libraries"
sudo dnf install autoconf automake libtool pkgconfig
sudo dnf install fuse-devel libxml2-devel libuuid-devel libicu-devel
sudo dnf install net-snmp-devel python3 python3-tkinter
```

#### ArchLinux

```bash
sudo pacman -S base-devel autoconf automake libtool pkgconfig
sudo pacman -S fuse2 libxml2 util-linux-libs icu
sudo pacman -S net-snmp python python-tk
```

### Minimum Version Requirements

- **FUSE**: >= 2.6.0
- **libxml2**: >= 2.6.16
- **UUID library**: >= 1.36 (Linux), >= 1.6 (macOS)
- **ICU**: >= 0.21
- **net-snmp**: >= 5.3 (optional)
- **Python**: >= 3.6 (for GUI)

## Build and install on Linux

### Step 1: Prepare the Build Environment

```bash
# Clone the repository (if not already done)
git clone https://github.com/LinearTapeFileSystem/ltfs.git
cd ltfs

# Generate configure script
./autogen.sh
```

### Step 2: Configure the Build

```bash
# Basic configuration
./configure

# Or with custom options:
./configure --prefix=/usr/local --enable-lintape

# For systems without SNMP (like macOS):
./configure --disable-snmp

# For debug build:
./configure --enable-debug
```

**Common configure options:**
- `--prefix=PATH`: Installation prefix (default: /usr/local)
- `--enable-lintape`: Enable IBM lin_tape driver support
- `--disable-snmp`: Disable SNMP support
- `--enable-debug`: Compile with debug symbols
- `--enable-fast`: Enable optimizations
- `--help`: Show all options

### Step 3: Build

```bash
# Build using all available CPU cores
make -j$(nproc)

# Or build with single thread (if errors occur)
make
```

### Step 4: Install

```bash
# Install to system
sudo make install

# Update library cache
sudo ldconfig -v
```

### Step 5: Post-Installation Setup

#### 1. Set up user permissions

```bash
# Add your user to the tape group
sudo usermod -a -G tape $USER

# Create tape group if it doesn't exist
if ! getent group tape > /dev/null; then
    sudo groupadd tape
    sudo usermod -a -G tape $USER
fi

# Log out and back in for changes to take effect
```

#### 2. Verify installation

```bash
# Check LTFS version
ltfs --version

# Check available commands
which ltfs mkltfs

# List tape drives (requires tape drive connected)
ltfs -o device_list
```

#### 3. Install LTFS GUI (optional)

```bash
# Using the installation script
./install_ltfs_gui.sh

# Or manually
chmod +x ltfs_gui.py
cp ltfs_gui.py ~/.local/bin/ltfs-gui
cp ltfs-gui.desktop ~/.local/share/applications/
```

## Troubleshooting Common Issues

### FUSE Issues

#### Problem: "fuse: failed to open /dev/fuse: Permission denied"

**Solution:**
```bash
# Check if FUSE is loaded
lsmod | grep fuse

# Load FUSE module if not loaded
sudo modprobe fuse

# Add to auto-load at boot
echo 'fuse' | sudo tee -a /etc/modules

# Check FUSE device permissions
ls -la /dev/fuse

# Fix permissions if needed
sudo chmod 666 /dev/fuse
```

#### Problem: "configure: error: Package requirements (fuse >= 2.6.0) were not met"

**Solution:**
```bash
# Ubuntu/Debian
sudo apt install libfuse-dev

# RHEL/CentOS/Fedora
sudo dnf install fuse-devel  # or yum install fuse-devel

# Verify FUSE version
pkg-config --modversion fuse
```

### ICU Issues

#### Problem: "icu-config not found" or "ICU not detected"

**Solution for Ubuntu 20.04+/Debian 10+:**
```bash
# Install ICU development package
sudo apt install libicu-dev icu-devtools

# Create dummy icu-config if still missing
if ! command -v icu-config &> /dev/null; then
    cat << 'EOF' | sudo tee /usr/local/bin/icu-config
#!/bin/bash
pkg-config "$@" icu-i18n icu-uc icu-io
EOF
    sudo chmod +x /usr/local/bin/icu-config
fi

# Verify ICU
pkg-config --modversion icu-i18n
```

**Solution for RHEL/CentOS:**
```bash
# Install ICU
sudo dnf install libicu-devel  # or yum install libicu-devel

# Set PKG_CONFIG_PATH if needed
export PKG_CONFIG_PATH="/usr/lib64/pkgconfig:$PKG_CONFIG_PATH"
```

### Tape Device Issues

#### Problem: "No tape drives found" or permission errors

**Solution:**
```bash
# Check for SCSI tape devices
ls -la /dev/st* /dev/nst* /dev/sg*

# Check tape device permissions
ls -la /dev/sg*

# Add user to tape group (if not done already)
sudo usermod -a -G tape $USER

# Set proper udev rules for tape devices
echo 'SUBSYSTEM=="scsi_generic", GROUP="tape", MODE="0664"' | sudo tee /etc/udev/rules.d/60-tape.rules
echo 'SUBSYSTEM=="scsi_tape", GROUP="tape", MODE="0664"' | sudo tee -a /etc/udev/rules.d/60-tape.rules

# Reload udev rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

### Build Issues

#### Problem: "genrb not found" or "pkgdata not found"

**Solution:**
```bash
# Ubuntu/Debian
sudo apt install icu-devtools

# RHEL/CentOS/Fedora
sudo dnf install libicu-devel

# Verify tools are available
which genrb pkgdata
```

#### Problem: Compilation errors with newer GCC

**Solution:**
```bash
# Use older GCC version if available
sudo apt install gcc-8 g++-8  # Ubuntu/Debian
export CC=gcc-8
export CXX=g++-8
./configure

# Or disable specific warnings
export CFLAGS="-Wno-error=stringop-truncation"
./configure
```

### Python GUI Issues

#### Problem: "tkinter not found" or GUI won't start

**Solution:**
```bash
# Ubuntu/Debian/Linux Mint
sudo apt install python3-tk

# RHEL/CentOS/Fedora
sudo dnf install python3-tkinter

# Test tkinter
python3 -c "import tkinter; print('tkinter OK')"

# Run GUI test
python3 test_ltfs_gui.py
```

### Runtime Issues

#### Problem: "ltfs: command not found" after installation

**Solution:**
```bash
# Check installation location
which ltfs || echo "Not in PATH"

# Add to PATH if installed in /usr/local
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Or create symlinks
sudo ln -sf /usr/local/bin/ltfs /usr/bin/ltfs
sudo ln -sf /usr/local/bin/mkltfs /usr/bin/mkltfs
```

#### Problem: "error while loading shared libraries"

**Solution:**
```bash
# Update library cache
sudo ldconfig -v

# Add library path if needed
echo '/usr/local/lib' | sudo tee -a /etc/ld.so.conf
sudo ldconfig

# Or set LD_LIBRARY_PATH
export LD_LIBRARY_PATH="/usr/local/lib:$LD_LIBRARY_PATH"
```

## Testing the Installation

```bash
# Test basic functionality
ltfs --version
mkltfs --help

# Test device detection (with tape drive connected)
ltfs -o device_list

# Test GUI (if installed)
./ltfs_gui.py

# Run comprehensive test
./test_ltfs_gui.py
```

## Quick Install Script

For a one-command installation on Ubuntu/Debian/Linux Mint:

```bash
curl -fsSL https://raw.githubusercontent.com/LinearTapeFileSystem/ltfs/master/scripts/install-ubuntu.sh | bash
```

**Note:** Always review scripts before running them. The above is an example - create your own install script as needed.

### Buildable Linux distributions

  | Dist                               | Arch    | Status                                                                                                                           |
  |:----------------------------------:|:-------:|:--------------------------------------------------------------------------------------------------------------------------------:|
  | RHEL 8                             | x86\_64 | OK - Not checked automatically                                                                                                   |
  | RHEL 8                             | ppc64le | OK - Not checked automatically                                                                                                   |
  | CentOS 8 (Rocky Linux)             | x86\_64 | ![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-centos8.yml/badge.svg)        |
  | CentOS 8 (Rocky Linux)             | ppc64le | OK - Not checked automatically                                                                                                   |
  | Fedora 28                          | x86\_64 | ![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-fedora28.yml/badge.svg)       |
  | Ubuntu 16.04 LTS                   | x86\_64 | ![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-ubuntu-xeneal.yml/badge.svg) |
  | Ubuntu 16.04 LTS                   | ppc64le | OK - Not checked automatically                                                                                                   |
  | Ubuntu 18.04 LTS                   | x86\_64 | ![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-ubuntu-bionic.yml/badge.svg) |
  | Ubuntu 18.04 LTS                   | ppc64le | OK - Not checked automatically                                                                                                   |
  | Ubuntu 20.04 LTS (Need icu-config) | x86\_64 | ![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-ubuntu-focal.yml/badge.svg) |
  | Debian 9                           | x86\_64 | ![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-debian9.yml/badge.svg)        |
  | Debian 10 (Need icu-config)        | x86\_64 | ![GH Action status](https://github.com/LinearTapeFileSystem/ltfs/actions/workflows/build-debian10.yml/badge.svg)       |
  | ArchLinux 2018.08.01               | x86\_64 | OK - Not checked automatically                                                                                                   |
  | ArchLinux 2018.12.31 (rolling)     | x86\_64 | OK - Not checked automatically                                                                                                   |

Currently, automatic build checking is working on GitHub Actions and Travis CI.

For Ubuntu20.04 and Debian10, dummy `icu-config` is needed in the build machine. See Issue [#153](https://github.com/LinearTapeFileSystem/ltfs/issues/153).

## Build and install on OSX (macOS)

### Recent Homebrew system setup

Before build on macOS, you need to configure the environment like below.

```
export ICU_PATH="/usr/local/opt/icu4c/bin"
export LIBXML2_PATH="/usr/local/opt/libxml2/bin"
export PKG_CONFIG_PATH="/usr/local/opt/icu4c/lib/pkgconfig:/usr/local/opt/libxml2/lib/pkgconfig"
export PATH="$PATH:$ICU_PATH:$LIBXML2_PATH"
```

### Old Homebrew system setup
Before build on OSX (macOS), some include path adjustment is required.

```
brew link --force icu4c
brew link --force libxml2
```

### Building LTFS
On OSX (macOS), snmp cannot be supported, you need to disable it on configure script. And may be, you need to specify LDFLAGS while running configure script to link some required frameworks, CoreFundation and IOKit.

```
./autogen.sh
LDFLAGS="-framework CoreFoundation -framework IOKit" ./configure --disable-snmp
make
make install
```

`./configure --help` shows various options for build and install.

#### Buildable macOS systems

  | OS            | Xcode | Package system | Status                                                                                                                                |
  |:-------------:|:-----:|:--------------:|:-------------------------------------------------------------------------------------------------------------------------------------:|
  | macOS 10.14.6 | 11.3  | Homebrew       | OK - Not checked automatically                                                                                                        |
  | macOS 10.15   | 12.4  | Homebrew       | OK - Not checked automatically                                                                                                        |
  | macOS 11      | 12.4  | Homebrew       | OK - Not checked automatically                                                                                                        |

## Build and install on FreeBSD

Note that on FreeBSD, the usual 3rd party man directory is /usr/local/man. Configure defaults to using /usr/local/share/man.  So, override it on the command line to avoid having man pages put in the wrong place.

```
./autogen.sh
./configure --prefix=/usr/local --mandir=/usr/local/man
make
make install
```

#### Buildable versions

  | Version | Arch    | Status                         |
  |:-------:|:-------:|:------------------------------:|
  | 11      | x86\_64 | OK - Not checked automatically |
  | 12      | x86\_64 | OK - Not checked automatically |

### Build and install on NetBSD

```
./autogen.sh
./configure
make
make install
```

#### Buildable versions

  | Version | Arch  | Status                         |
  |:-------:|:-----:|:------------------------------:|
  | 8.1     | amd64 | OK - Not checked automatically |
  | 8.0     | i386  | OK - Not checked automatically |
  | 7.2     | amd64 | OK - Not checked automatically |

## Contributing

Please read [CONTRIBUTING.md](.github/CONTRIBUTING.md) for details on our code of conduct, and the process for submitting pull requests to us.

## License

This project is licensed under the BSD License - see the [LICENSE](LICENSE) file for details
