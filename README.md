# Immich Variety Bridge

Requirements:
- `python`
- `make`
- [Immich](https://immich.app/docs/api/) API access
- [Variety](https://github.com/varietywalls/variety) (or other wallpaper manager that uses a local directory as a source)

## What it does

This script acts as a bridge between [Immich](https://immich.app/) and [Variety](https://github.com/varietywalls/variety) wallpaper manager (or any other wallpaper manager that uses a local directory as a source), allowing the use of Immich photos as a wallpaper source by downloading them to a local directory.

Since Variety does not have a way to sync with Immich or to cap the number or size of wallpapers it downloads, this script provides a way to do both.

The script will keep running in a loop, downloading new images from Immich and deleting old images to keep the local directory size under control (if those limits are set). To just download once, use `make run-once`.

## Setup

1.  **Clone the repository** (if you haven't already).
2.  **Configure environment variables**:
    - Copy `.env.example` to `.env`:
      ```bash
      cp .env.example .env
      ```
    - Edit `.env` and decide on the options you want to use. 
3.  **Run the script**:
    The Makefile handles virtual environment creation and dependency installation.
    ```bash
    make run
    # to run in a lopp, or to only download once:
    make run-once
    ```
