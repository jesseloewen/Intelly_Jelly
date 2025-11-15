import os
import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import math

logger = logging.getLogger(__name__)


class LibraryBrowser:
    """Browse and manage files in the library path."""
    
    def __init__(self, library_path: str):
        self.library_path = library_path
        self.video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg'}
        self.subtitle_extensions = {'.srt', '.sub', '.vtt', '.ass', '.ssa'}
        self.supported_extensions = self.video_extensions | self.subtitle_extensions | {'.mp3', '.flac', '.wav', '.aac', '.m4a', '.pdf', '.epub', '.mobi'}
    
    def update_library_path(self, new_path: str):
        """Update the library path."""
        self.library_path = new_path
        logger.info(f"Library path updated to: {new_path}")
    
    def _get_all_files(self) -> List[Dict]:
        """Recursively get all files in the library path."""
        files = []
        
        if not os.path.exists(self.library_path):
            logger.warning(f"Library path does not exist: {self.library_path}")
            return files
        
        try:
            for root, dirs, filenames in os.walk(self.library_path):
                for filename in filenames:
                    file_path = os.path.join(root, filename)
                    file_ext = os.path.splitext(filename)[1].lower()
                    
                    # Only include supported file types
                    if file_ext in self.supported_extensions:
                        relative_path = os.path.relpath(file_path, self.library_path)
                        file_size = os.path.getsize(file_path)
                        modified_time = os.path.getmtime(file_path)
                        
                        files.append({
                            'filename': filename,
                            'full_path': file_path,
                            'relative_path': relative_path,
                            'directory': os.path.dirname(relative_path),
                            'extension': file_ext,
                            'size': file_size,
                            'modified': modified_time,
                            'is_video': file_ext in self.video_extensions,
                            'is_subtitle': file_ext in self.subtitle_extensions
                        })
        
        except Exception as e:
            logger.error(f"Error scanning library path: {type(e).__name__}: {e}", exc_info=True)
        
        return files
    
    def _get_directory_contents(self, current_dir: str) -> Tuple[List[Dict], List[Dict]]:
        """
        Get folders and files in a specific directory (non-recursive).
        
        Args:
            current_dir: Relative path from library root (empty string for root)
            
        Returns:
            Tuple of (folders_list, files_list)
        """
        folders = []
        files = []
        
        # Build full path
        if current_dir:
            full_path = os.path.join(self.library_path, current_dir)
        else:
            full_path = self.library_path
        
        if not os.path.exists(full_path):
            logger.warning(f"Directory does not exist: {full_path}")
            return folders, files
        
        try:
            # Get immediate children only
            items = os.listdir(full_path)
            
            for item in items:
                item_path = os.path.join(full_path, item)
                
                if os.path.isdir(item_path):
                    # It's a folder
                    folder_rel_path = os.path.join(current_dir, item) if current_dir else item
                    
                    # Count files in this folder (recursively)
                    file_count = 0
                    try:
                        for root, dirs, filenames in os.walk(item_path):
                            file_count += len([f for f in filenames if os.path.splitext(f)[1].lower() in self.supported_extensions])
                    except:
                        pass
                    
                    folders.append({
                        'name': item,
                        'relative_path': folder_rel_path,
                        'full_path': item_path,
                        'file_count': file_count,
                        'is_folder': True
                    })
                
                elif os.path.isfile(item_path):
                    # It's a file
                    file_ext = os.path.splitext(item)[1].lower()
                    
                    # Only include supported file types
                    if file_ext in self.supported_extensions:
                        file_rel_path = os.path.join(current_dir, item) if current_dir else item
                        file_size = os.path.getsize(item_path)
                        modified_time = os.path.getmtime(item_path)
                        is_video = file_ext in self.video_extensions
                        
                        # Check for subtitle if it's a video
                        has_subtitle = False
                        if is_video:
                            subtitle_path = self.find_related_subtitle(item_path)
                            has_subtitle = subtitle_path is not None
                        
                        files.append({
                            'filename': item,
                            'full_path': item_path,
                            'relative_path': file_rel_path,
                            'directory': current_dir,
                            'extension': file_ext,
                            'size': file_size,
                            'modified': modified_time,
                            'is_video': is_video,
                            'is_subtitle': file_ext in self.subtitle_extensions,
                            'has_subtitle': has_subtitle,
                            'is_folder': False
                        })
        
        except Exception as e:
            logger.error(f"Error scanning directory: {type(e).__name__}: {e}", exc_info=True)
        
        # Sort folders alphabetically
        folders.sort(key=lambda x: x['name'].lower())
        
        return folders, files
    
    def get_files_paginated(self, page: int = 1, per_page: int = 50, search: Optional[str] = None, 
                           sort_by: str = 'modified', sort_order: str = 'desc', 
                           current_dir: str = '') -> Dict:
        """
        Get files with pagination, supporting directory navigation.
        
        Args:
            page: Page number (1-indexed)
            per_page: Number of items per page
            search: Optional search filter
            sort_by: Field to sort by (filename, modified, size)
            sort_order: Sort order (asc, desc)
            current_dir: Current directory relative to library root (empty for root)
            
        Returns:
            Dictionary with folders, files, pagination info, and stats
        """
        # If searching, use recursive search across all files
        if search:
            all_files = self._get_all_files()
            search_lower = search.lower()
            all_files = [f for f in all_files if search_lower in f['filename'].lower() 
                        or search_lower in f['relative_path'].lower()]
            folders = []
        else:
            # Get directory contents (non-recursive)
            folders, all_files = self._get_directory_contents(current_dir)
        
        # Sort files
        reverse = (sort_order == 'desc')
        if sort_by == 'filename':
            all_files.sort(key=lambda x: x['filename'].lower(), reverse=reverse)
        elif sort_by == 'size':
            all_files.sort(key=lambda x: x['size'], reverse=reverse)
        else:  # modified
            all_files.sort(key=lambda x: x['modified'], reverse=reverse)
        
        # Combine folders and files for pagination
        all_items = folders + all_files
        
        # Calculate pagination
        total_items = len(all_items)
        total_pages = math.ceil(total_items / per_page) if total_items > 0 else 1
        page = max(1, min(page, total_pages))  # Clamp page to valid range
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_items = all_items[start_idx:end_idx]
        
        # Calculate parent directory
        parent_dir = None
        if current_dir:
            parent_dir = os.path.dirname(current_dir)
        
        # Get all files recursively for stats
        all_files_recursive = self._get_all_files()
        
        return {
            'items': page_items,
            'current_dir': current_dir,
            'parent_dir': parent_dir,
            'has_parent': bool(current_dir),
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_items': total_items,
                'total_pages': total_pages,
                'has_previous': page > 1,
                'has_next': page < total_pages
            },
            'stats': {
                'total_files': len(all_files_recursive),
                'video_files': len([f for f in all_files_recursive if f.get('is_video')]),
                'subtitle_files': len([f for f in all_files_recursive if f.get('is_subtitle')]),
                'total_size': sum(f.get('size', 0) for f in all_files_recursive)
            }
        }
    
    def find_related_subtitle(self, video_path: str) -> Optional[str]:
        """Find subtitle file with matching base name."""
        video_dir = os.path.dirname(video_path)
        video_base = os.path.splitext(os.path.basename(video_path))[0]
        
        for ext in self.subtitle_extensions:
            subtitle_path = os.path.join(video_dir, video_base + ext)
            if os.path.exists(subtitle_path):
                return subtitle_path
        
        return None
    
    def rename_file(self, old_path: str, new_name: str, rename_subtitle: bool = True) -> Dict:
        """
        Rename a file and optionally its related subtitle.
        Supports both simple renames and moving to different directories.
        
        Args:
            old_path: Full path to the file to rename
            new_name: New filename or relative path (e.g., "newname.ext" or "subfolder/newname.ext")
            rename_subtitle: If True and file is video, rename matching subtitle too
            
        Returns:
            Dictionary with success status and messages
        """
        result = {
            'success': False,
            'message': '',
            'renamed_files': []
        }
        
        try:
            if not os.path.exists(old_path):
                result['message'] = f"File not found: {old_path}"
                return result
            
            old_dir = os.path.dirname(old_path)
            old_filename = os.path.basename(old_path)
            old_ext = os.path.splitext(old_filename)[1]
            
            # Check if new_name contains directory separators (indicates a path)
            if '/' in new_name or '\\' in new_name:
                # new_name is a relative path from library root
                # Normalize path separators
                new_name_normalized = new_name.replace('\\', '/')
                
                # Build full path from library root
                new_path = os.path.join(self.library_path, new_name_normalized)
                
                # Ensure extension is preserved
                new_base = os.path.splitext(new_path)[0]
                new_path = new_base + old_ext
                new_dir = os.path.dirname(new_path)
                new_filename = os.path.basename(new_path)
            else:
                # Simple filename rename in same directory
                new_base = os.path.splitext(new_name)[0]
                new_filename = new_base + old_ext
                new_path = os.path.join(old_dir, new_filename)
                new_dir = old_dir
            
            # Check if destination already exists
            if os.path.exists(new_path) and new_path != old_path:
                result['message'] = f"Destination file already exists: {new_filename}"
                return result
            
            # Create destination directory if it doesn't exist
            os.makedirs(new_dir, exist_ok=True)
            
            # Rename/move the main file
            os.rename(old_path, new_path)
            result['renamed_files'].append({
                'old': old_path,
                'new': new_path,
                'type': 'main'
            })
            logger.info(f"Renamed file: {old_path} -> {new_path}")
            
            # If it's a video and rename_subtitle is True, try to rename subtitle
            if rename_subtitle and old_ext.lower() in self.video_extensions:
                subtitle_path = self.find_related_subtitle(old_path)
                if subtitle_path:
                    subtitle_ext = os.path.splitext(subtitle_path)[1]
                    # Get base name from new path (without extension)
                    new_base_name = os.path.splitext(os.path.basename(new_path))[0]
                    new_subtitle_path = os.path.join(new_dir, new_base_name + subtitle_ext)
                    
                    try:
                        os.rename(subtitle_path, new_subtitle_path)
                        result['renamed_files'].append({
                            'old': subtitle_path,
                            'new': new_subtitle_path,
                            'type': 'subtitle'
                        })
                        logger.info(f"Renamed subtitle: {subtitle_path} -> {new_subtitle_path}")
                    except Exception as e:
                        logger.warning(f"Failed to rename subtitle: {e}")
            
            result['success'] = True
            result['message'] = f"Successfully renamed {len(result['renamed_files'])} file(s)"
            
        except Exception as e:
            logger.error(f"Error renaming file: {type(e).__name__}: {e}", exc_info=True)
            result['message'] = f"Error: {str(e)}"
        
        return result
    
    def get_file_info(self, file_path: str) -> Optional[Dict]:
        """Get detailed information about a specific file."""
        if not os.path.exists(file_path):
            return None
        
        filename = os.path.basename(file_path)
        file_ext = os.path.splitext(filename)[1].lower()
        relative_path = os.path.relpath(file_path, self.library_path)
        
        info = {
            'filename': filename,
            'full_path': file_path,
            'relative_path': relative_path,
            'directory': os.path.dirname(relative_path),
            'extension': file_ext,
            'size': os.path.getsize(file_path),
            'modified': os.path.getmtime(file_path),
            'is_video': file_ext in self.video_extensions,
            'is_subtitle': file_ext in self.subtitle_extensions
        }
        
        # Check for related subtitle if it's a video
        if info['is_video']:
            subtitle_path = self.find_related_subtitle(file_path)
            info['has_subtitle'] = subtitle_path is not None
            info['subtitle_path'] = subtitle_path
        
        return info
