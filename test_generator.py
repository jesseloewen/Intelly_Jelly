"""
Test Data Generator
Creates sample files for testing Intelly Jelly.
"""

import os
from pathlib import Path
import random

# Sample test filenames
TEST_FILES = [
    # Movies
    "The.Matrix.1999.1080p.BluRay.x264-GROUP.mkv",
    "Inception.2010.720p.WEB-DL.AAC2.0.H.264.mkv",
    "Interstellar_2014_2160p_4K_UHD.mp4",
    "the.shawshank.redemption.1994.bluray.1080p.mkv",
    "Avatar The Way of Water (2022) [1080p].mp4",
    
    # TV Shows
    "Breaking.Bad.S01E01.Pilot.1080p.BluRay.x264.mkv",
    "Game.of.Thrones.S08E06.FINAL.720p.WEB.h264.mkv",
    "the_mandalorian_s02e08_1080p_web_h264.mkv",
    "Stranger Things S04E09 1080p NF WEB-DL.mkv",
    "better.call.saul.s06e13.finale.1080p.mkv",
    
    # Music
    "01 - Artist Name - Song Title.mp3",
    "Pink Floyd - Comfortably Numb (Live).flac",
    "The_Beatles-Hey_Jude.mp3",
    "Queen - Bohemian Rhapsody (Remastered).flac",
    "02-daft_punk-get_lucky.mp3",
    
    # Documentaries
    "Planet.Earth.II.S01E01.Islands.2160p.BluRay.x265.mkv",
    "cosmos_a_spacetime_odyssey_s01e01_1080p.mp4",
    "Our Planet 2019 S01E01 One Planet 4K HDR.mkv",
    
    # Messy filenames
    "some.random.movie.[2023].WEBRip.x264-YIFY.avi",
    "TV_Show_Name_-_s01e01_-_pilot_[720p]_[h264].mp4",
    "[SubGroup] Anime Title - 01 (1080p).mkv",
]


def create_test_files(directory: str = "test_downloads", count: int = 10):
    """Create test files in the specified directory."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    
    print(f"Creating {count} test files in {directory}/\n")
    
    # Select random files
    selected = random.sample(TEST_FILES, min(count, len(TEST_FILES)))
    
    for filename in selected:
        file_path = path / filename
        
        # Create a small file with some content
        with open(file_path, 'w') as f:
            f.write(f"Test file: {filename}\n")
            f.write("This is a sample file for testing Intelly Jelly.\n")
            f.write("="*50 + "\n")
        
        print(f"✓ Created: {filename}")
    
    print(f"\n✓ {count} test files created successfully!")
    print(f"\nTest files are in: {path.absolute()}")


def create_test_directories():
    """Create all test directories."""
    directories = [
        "test_downloads",
        "test_completed",
        "test_library"
    ]
    
    print("Creating test directories...\n")
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✓ Created: {directory}/")
    
    print("\n✓ All test directories created!")


def main():
    """Main entry point."""
    print("\n" + "="*60)
    print("🍇 Intelly Jelly - Test Data Generator")
    print("="*60 + "\n")
    
    # Create directories
    create_test_directories()
    print()
    
    # Create test files
    try:
        count = int(input("\nHow many test files to create? (1-22, default 10): ") or "10")
        count = max(1, min(22, count))
    except ValueError:
        count = 10
    
    create_test_files(count=count)
    
    print("\n" + "="*60)
    print("Ready to test!")
    print("="*60)
    print("\nNext steps:")
    print("1. Run: python main.py")
    print("2. Open: http://localhost:7000")
    print("3. Watch the files get processed automatically")
    print("\nOr move files to test_downloads/ manually to trigger processing.\n")


if __name__ == '__main__':
    main()
