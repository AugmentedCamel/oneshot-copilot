"""
Data Augmentation Service

Multiplies training data by generating augmented versions of images:
- Horizontal flip (mirror)
- Brightness variations (darker/brighter)

Uses prefixes to clearly identify augmented images and prevent re-augmenting.
"""

import os
import logging
from pathlib import Path
from typing import Optional
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)

# Prefixes for augmented images - used to skip already-augmented files
AUGMENT_PREFIXES = ("aug_flip_", "aug_dark_", "aug_bright_")

# Default data directory
DEFAULT_DATA_DIR = "data_lake/proc_change_coffeefilter"


class DataAugmentorService:
    """
    Service for augmenting training data images.
    
    Generates mirrored and brightness-adjusted copies of original images.
    Naming convention ensures augmented images are clearly identifiable.
    """
    
    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        
    def augment_folder(self, folder_path: str) -> dict:
        """
        Augment all original images in a folder.
        
        Skips files that already have augmentation prefixes to avoid
        generating aug_flip_aug_flip_ type names.
        
        Returns:
            dict with counts of generated images
        """
        folder = Path(folder_path)
        if not folder.exists():
            logger.warning(f"Folder does not exist: {folder_path}")
            return {"error": f"Folder not found: {folder_path}", "generated": 0}
        
        # Find original images (not already augmented)
        images = [
            f for f in folder.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png')
            and not f.name.startswith(AUGMENT_PREFIXES)
        ]
        
        logger.info(f"Processing {folder_path}: found {len(images)} original images")
        
        flip_count = 0
        dark_count = 0
        bright_count = 0
        skipped = 0
        
        for img_path in images:
            try:
                with Image.open(img_path) as img:
                    # Convert to RGB if needed (handles RGBA, palette images, etc.)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    # 1. Horizontal Flip (Mirror)
                    flip_path = folder / f"aug_flip_{img_path.name}"
                    if not flip_path.exists():
                        flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
                        flipped.save(flip_path, quality=95)
                        flip_count += 1
                    else:
                        skipped += 1
                    
                    # 2. Brightness - Darker (70%)
                    dark_path = folder / f"aug_dark_{img_path.name}"
                    if not dark_path.exists():
                        enhancer = ImageEnhance.Brightness(img)
                        darker = enhancer.enhance(0.7)
                        darker.save(dark_path, quality=95)
                        dark_count += 1
                    else:
                        skipped += 1
                    
                    # 3. Brightness - Brighter (130%)
                    bright_path = folder / f"aug_bright_{img_path.name}"
                    if not bright_path.exists():
                        enhancer = ImageEnhance.Brightness(img)
                        brighter = enhancer.enhance(1.3)
                        brighter.save(bright_path, quality=95)
                        bright_count += 1
                    else:
                        skipped += 1
                        
            except Exception as e:
                logger.error(f"Failed to augment {img_path}: {e}")
                continue
        
        total_generated = flip_count + dark_count + bright_count
        logger.info(f"  -> Generated {total_generated} new images (skipped {skipped} existing)")
        
        return {
            "folder": str(folder_path),
            "original_images": len(images),
            "flip_generated": flip_count,
            "dark_generated": dark_count,
            "bright_generated": bright_count,
            "total_generated": total_generated,
            "skipped_existing": skipped
        }
    
    def augment_all(self) -> dict:
        """
        Augment all class folders in the data directory.
        
        Returns:
            dict with summary of all augmentations
        """
        data_path = Path(self.data_dir)
        if not data_path.exists():
            return {"error": f"Data directory not found: {self.data_dir}"}
        
        results = []
        total_generated = 0
        
        for class_folder in sorted(data_path.iterdir()):
            if class_folder.is_dir():
                result = self.augment_folder(str(class_folder))
                results.append(result)
                total_generated += result.get("total_generated", 0)
        
        return {
            "data_dir": self.data_dir,
            "folders_processed": len(results),
            "total_images_generated": total_generated,
            "details": results
        }
    
    def get_stats(self) -> dict:
        """Get current augmentation statistics for the data directory."""
        data_path = Path(self.data_dir)
        if not data_path.exists():
            return {"error": f"Data directory not found: {self.data_dir}"}
        
        stats = []
        for class_folder in sorted(data_path.iterdir()):
            if class_folder.is_dir():
                all_images = list(class_folder.glob("*.jpg")) + list(class_folder.glob("*.png"))
                originals = [f for f in all_images if not f.name.startswith(AUGMENT_PREFIXES)]
                augmented = [f for f in all_images if f.name.startswith(AUGMENT_PREFIXES)]
                
                stats.append({
                    "class": class_folder.name,
                    "original": len(originals),
                    "augmented": len(augmented),
                    "total": len(all_images)
                })
        
        return {
            "data_dir": self.data_dir,
            "classes": stats
        }


# Singleton instance
data_augmentor = DataAugmentorService()
