"""
Intelly Jelly - Intelligent Media Organization
Main application entry point.
"""

import sys
import time
import threading
from pathlib import Path

from backend.config_manager import get_config
from backend.file_watcher import get_watcher_manager
from backend.ai_processor import get_ai_processor
from backend.file_organizer import get_file_organizer
from web.app import create_app


def check_env_file():
    """Check if .env file exists and warn if not."""
    if not Path('.env').exists():
        print("⚠️  Warning: .env file not found!")
        print("   Copy .env.example to .env and add your API keys if using OpenAI or Google.")
        print("   For Ollama, no API key is needed.\n")


def start_backend():
    """Start all backend services."""
    print("Starting Intelly Jelly backend services...\n")
    
    # Load configuration
    config = get_config()
    print(f"✓ Configuration loaded")
    print(f"  - Downloading: {config.get('DOWNLOADING_PATH')}")
    print(f"  - Completed: {config.get('COMPLETED_PATH')}")
    print(f"  - Library: {config.get('LIBRARY_PATH')}")
    print(f"  - AI Provider: {config.get('AI_PROVIDER')}")
    print(f"  - AI Model: {config.get('AI_MODEL')}\n")
    
    # Start file watcher
    watcher = get_watcher_manager()
    watcher.start()
    print("✓ File watcher started\n")
    
    # Start AI processor
    ai_processor = get_ai_processor()
    ai_processor.start()
    print("✓ AI processor started\n")
    
    # Start file organizer
    organizer = get_file_organizer()
    organizer.start()
    print("✓ File organizer started\n")


def start_web_server():
    """Start the Flask web server."""
    print("Starting web interface on http://localhost:7000\n")
    print("=" * 60)
    print("🍇 Intelly Jelly is running!")
    print("=" * 60)
    print("Web Interface: http://localhost:7000")
    print("Settings: http://localhost:7000/settings")
    print("\nPress Ctrl+C to stop\n")
    
    app = create_app()
    app.run(host='0.0.0.0', port=7000, debug=False, use_reloader=False)


def main():
    """Main application entry point."""
    print("\n" + "=" * 60)
    print("🍇 Intelly Jelly - Intelligent Media Organization")
    print("=" * 60 + "\n")
    
    # Check environment
    check_env_file()
    
    try:
        # Start backend services
        start_backend()
        
        # Start web server (blocking)
        start_web_server()
    
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("Shutting down Intelly Jelly...")
        print("=" * 60)
        
        # Cleanup
        get_watcher_manager().stop()
        get_ai_processor().stop()
        get_file_organizer().stop()
        
        print("✓ All services stopped")
        print("Goodbye! 👋\n")
        sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
