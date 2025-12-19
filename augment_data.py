"""
Data Augmentation CLI Script

Run directly from PowerShell to augment training data.
Usage: python augment_data.py
"""

import os
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app.services.data_augmentor import DataAugmentorService


def main():
    print("=" * 60)
    print("Data Augmentation Tool")
    print("=" * 60)
    
    augmentor = DataAugmentorService()
    
    # Show current stats first
    print("\nCurrent stats:")
    stats = augmentor.get_stats()
    for cls in stats.get("classes", []):
        print(f"  {cls['class']}: {cls['original']} original, {cls['augmented']} augmented")
    
    # Run augmentation
    print("\nRunning augmentation...")
    result = augmentor.augment_all()
    
    # Show results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for detail in result.get("details", []):
        folder = Path(detail["folder"]).name
        print(f"\n{folder}:")
        print(f"  Original images: {detail['original_images']}")
        print(f"  Flip generated:  {detail['flip_generated']}")
        print(f"  Dark generated:  {detail['dark_generated']}")
        print(f"  Bright generated: {detail['bright_generated']}")
        print(f"  Skipped existing: {detail['skipped_existing']}")
    
    print("\n" + "=" * 60)
    print(f"TOTAL: {result.get('total_images_generated', 0)} new images generated")
    print("=" * 60)


if __name__ == "__main__":
    main()
