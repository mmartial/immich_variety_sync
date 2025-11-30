import os
import time
import requests
import argparse
import random
from PIL import Image, ImageFilter, ImageOps
from io import BytesIO

from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
IMMICH_URL = os.getenv("IMMICH_URL", "http://192.168.1.100:2283").rstrip('/')
API_KEY = os.getenv("API_KEY", "")
ALBUM_IDS = [x.strip() for x in os.getenv("ALBUM_IDS", "").split(",") if x.strip()]
ALBUMS_FAVORITES = os.getenv("ALBUMS_FAVORITES", "True").lower() == "true"
DOWNLOAD_PATH = os.getenv("DOWNLOAD_PATH", "./wallpapers")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", 600)) # 10 minutes

# Advanced Options
RANDOM_SELECT = int(os.getenv("RANDOM_SELECT", 0)) # 0 = All
MAX_IMAGES = int(os.getenv("MAX_IMAGES", 0)) # 0 = Unlimited
MAX_LOCAL_GB = float(os.getenv("MAX_LOCAL_GB", 0)) # 0 = Unlimited
TARGET_SIZE = os.getenv("TARGET_SIZE", "") # Format: "1920x1080"

HEADERS = {"x-api-key": API_KEY, "Accept": "application/json"}

def get_assets():
    """Fetches all valid asset objects from Immich. Returns (assets, has_error)."""
    assets = {}
    has_error = False
    
    # Fetch Albums
    for album in ALBUM_IDS:
        try:
            print(f" [Sync] Fetching album {album}...")
            r = requests.get(f"{IMMICH_URL}/api/albums/{album}", headers=HEADERS)
            if r.status_code == 200:
                items = r.json()['assets']
                print(f" [Sync] Found {len(items)} items in album {album}.")
                for item in items:
                    assets[item['id']] = item
            else:
                print(f" [Sync] Error fetching album {album}: {r.status_code} {r.text}")
                has_error = True
        except Exception as e:
            print(f" [Sync] Error fetching album {album}: {e}")
            has_error = True
            
    return assets, has_error

def get_filename(asset):
    """Returns the filename for an asset: <original_name>-<id>.<ext>"""
    asset_id = asset['id']
    original_name = asset.get('originalFileName', 'img')
    base, ext = os.path.splitext(original_name)
    # Sanitize base name slightly to avoid path issues
    base = "".join(c for c in base if c.isalnum() or c in (' ', '-', '_')).strip()
    return f"{base}-{asset_id}{ext}"

def resize_and_pad(image_content, target_size_str, filename="Image"):
    """
    Resizes image to fit within target_size_str (WxH) and pads with blurred version.
    Returns bytes of the processed image.
    """
    try:
        w_str, h_str = target_size_str.lower().split('x')
        target_w, target_h = int(w_str), int(h_str)
    except ValueError:
        print(f" [Resize] Invalid TARGET_SIZE format: {target_size_str}. Skipping resize.")
        return image_content

    try:
        img = Image.open(BytesIO(image_content))
        
        # Log original details
        original_size = img.size
        exif = img.getexif()
        orientation = exif.get(0x0112)
        
        rotation_msg = ""
        if orientation and orientation != 1:
            rotation_msg = f", EXIF Orientation: {orientation}"
            
        print(f" [Resize] {filename} Original: {original_size[0]}x{original_size[1]}{rotation_msg} -> {target_size_str}")

        img = ImageOps.exif_transpose(img)
        
        # Calculate aspect ratios
        target_ratio = target_w / target_h
        img_ratio = img.width / img.height
        
        # Determine new size for the main image
        if img_ratio > target_ratio:
            # Image is wider than target
            new_w = target_w
            new_h = int(target_w / img_ratio)
        else:
            # Image is taller than target
            new_h = target_h
            new_w = int(target_h * img_ratio)
            
        resized_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        # Create background (blurred version of original, resized to cover)
        # To cover, we need to scale so the smaller dimension matches the target
        if img_ratio > target_ratio:
            # Wider: scale height to match target height
            bg_h = target_h
            bg_w = int(target_h * img_ratio)
        else:
            # Taller: scale width to match target width
            bg_w = target_w
            bg_h = int(target_w / img_ratio)
            
        bg_img = img.resize((bg_w, bg_h), Image.Resampling.BICUBIC)
        bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=20))
        
        # Center crop the background to target size
        left = (bg_w - target_w) / 2
        top = (bg_h - target_h) / 2
        right = (bg_w + target_w) / 2
        bottom = (bg_h + target_h) / 2
        bg_img = bg_img.crop((left, top, right, bottom))
        
        # Paste resized image onto background
        paste_x = (target_w - new_w) // 2
        paste_y = (target_h - new_h) // 2
        bg_img.paste(resized_img, (paste_x, paste_y))
        
        # Save to bytes
        output = BytesIO()
        # Preserve format if possible, default to JPEG if not
        fmt = img.format if img.format else 'JPEG'
        bg_img.save(output, format=fmt, quality=95)
        return output.getvalue()
        
    except Exception as e:
        print(f" [Resize] Error processing image: {e}")
        return image_content


def download_asset(asset, target_dir):
    """Downloads a single asset if it doesn't exist."""
    filename = get_filename(asset)
    path = os.path.join(target_dir, filename)
    
    if os.path.exists(path):
        # Update mtime to mark as "recently used" so it doesn't get deleted by rotation?
        # Actually, for rotation, we probably want to keep the original download time 
        # OR update it to keep it fresh. Let's update mtime so it stays in the rotation.
        os.utime(path, None) 
        return False # Already exists
        
    print(f" [Download] Downloading {filename}...")
    try:
        r = requests.get(f"{IMMICH_URL}/api/assets/{asset['id']}/original", headers=HEADERS, stream=True)
        if r.status_code == 200:
            content = r.content
            if TARGET_SIZE:
                content = resize_and_pad(content, TARGET_SIZE, filename)
                
            with open(path, 'wb') as f:
                f.write(content)
            return True
        else:
            print(f" [Download] Failed to download {asset['id']}: {r.status_code}")
    except Exception as e:
        print(f" [Download] Error downloading {asset['id']}: {e}")
        
    return False

def enforce_limits(target_dir, protected_filenames=set()):
    """Deletes oldest files if limits are exceeded, skipping protected files."""
    if MAX_IMAGES <= 0 and MAX_LOCAL_GB <= 0:
        return

    files = []
    total_size = 0
    
    # Gather file stats
    for f in os.listdir(target_dir):
        path = os.path.join(target_dir, f)
        if os.path.isfile(path) and not f.startswith('.'):
            # Skip protected files from being candidates for deletion
            if f in protected_filenames:
                continue
                
            stat = os.stat(path)
            files.append({'path': path, 'mtime': stat.st_mtime, 'size': stat.st_size})
            total_size += stat.st_size
            
    # Sort by mtime (oldest first)
    files.sort(key=lambda x: x['mtime'])
    
    deleted_count = 0
    
    # Check Count Limit
    while MAX_IMAGES > 0 and len(files) > MAX_IMAGES:
        to_delete = files.pop(0) # Remove oldest
        print(f" [Limit] Max images exceeded. Deleting {os.path.basename(to_delete['path'])}")
        try:
            os.remove(to_delete['path'])
            total_size -= to_delete['size']
            deleted_count += 1
        except Exception as e:
            print(f"Error deleting {to_delete['path']}: {e}")

    # Check Size Limit
    max_bytes = MAX_LOCAL_GB * 1024 * 1024 * 1024
    while MAX_LOCAL_GB > 0 and total_size > max_bytes and files:
        to_delete = files.pop(0) # Remove oldest
        print(f" [Limit] Max size exceeded ({total_size/1024/1024:.2f}MB). Deleting {os.path.basename(to_delete['path'])}")
        try:
            os.remove(to_delete['path'])
            total_size -= to_delete['size']
            deleted_count += 1
        except Exception as e:
            print(f"Error deleting {to_delete['path']}: {e}")
            
    if deleted_count > 0:
        print(f" [Limit] Cleanup complete. Removed {deleted_count} files.")

def sync_loop(once=False):
    if not os.path.exists(DOWNLOAD_PATH):
        os.makedirs(DOWNLOAD_PATH)
        
    while True:
        print(f"--- Starting Sync at {time.ctime()} ---")
        assets, has_error = get_assets()
        
        # 0. Identify Orphans & Protected Files
        valid_asset_ids = set(assets.keys())
        protected_filenames = set()
        
        # Build protected set from favorites (only if ALBUMS_FAVORITES is True)
        if ALBUMS_FAVORITES:
            for asset in assets.values():
                if asset.get('isFavorite'):
                    protected_filenames.add(get_filename(asset))
        
        local_files = os.listdir(DOWNLOAD_PATH)
        
        if not has_error:
            for f in local_files:
                if f.startswith('.'): continue
                
                # Orphan check
                is_valid = False
                for aid in valid_asset_ids:
                    if aid in f: 
                        is_valid = True
                        break
                
                if not is_valid:
                    print(f" [Cleanup] Removing orphan {f} (not found in current Immich assets)")
                    try:
                        os.remove(os.path.join(DOWNLOAD_PATH, f))
                    except:
                        pass
        else:
            print(" [Cleanup] Skipping orphan removal due to fetch errors.")

        # 1. Select Assets to Download
        if ALBUMS_FAVORITES:
            favorites = [a for a in assets.values() if a.get('isFavorite')]
            others = [a for a in assets.values() if not a.get('isFavorite')]
            selection = favorites[:] # Start with all favorites
        else:
            favorites = []
            others = list(assets.values())
            selection = []
        
        if RANDOM_SELECT > 0:
            # Randomly select from the non-favorites (or all if ALBUMS_FAVORITES is False)
            if len(others) > RANDOM_SELECT:
                print(f" [Select] Randomly selecting {RANDOM_SELECT} out of {len(others)} assets.")
                selection.extend(random.sample(others, RANDOM_SELECT))
            else:
                selection.extend(others)
        else:
            # Select all
            selection.extend(others)
            
        # 2. Download
        downloaded_count = 0
        for asset in selection:
            if download_asset(asset, DOWNLOAD_PATH):
                downloaded_count += 1
                
        # 3. Enforce Limits (Rotation)
        enforce_limits(DOWNLOAD_PATH, protected_filenames)

        print(f"--- Sync Complete. Downloaded: {downloaded_count}. ---")
        
        if once:
            break
            
        print(f"Sleeping for {SYNC_INTERVAL} seconds...")
        time.sleep(SYNC_INTERVAL)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Immich to Folder Sync")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()
    
    if not API_KEY:
        print("Error: API_KEY environment variable not set.")
        exit(1)
        
    sync_loop(once=args.once)
