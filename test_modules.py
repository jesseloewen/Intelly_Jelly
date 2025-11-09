"""Quick test script to verify all modules work."""
import sys
sys.path.insert(0, '.')

print("Testing Intelly Jelly modules...\n")

# Test 1: Config Manager
print("1. Testing Config Manager...")
from backend.config_manager import get_config
config = get_config()
print(f"   ✓ Config loaded")
print(f"   - Provider: {config.get('AI_PROVIDER')}")
print(f"   - Model: {config.get('AI_MODEL')}")

# Test 2: Job Store
print("\n2. Testing Job Store...")
from backend.job_store import get_job_store, JobStatus
store = get_job_store()
test_job = store.create_job('test_file.txt')
print(f"   ✓ Created test job: {test_job}")
job = store.get_job(test_job)
print(f"   ✓ Retrieved job: {job['original_filename']}")
store.delete_job(test_job)
print(f"   ✓ Deleted test job")

# Test 3: File Watcher
print("\n3. Testing File Watcher...")
from backend.file_watcher import get_watcher_manager
watcher = get_watcher_manager()
print(f"   ✓ File watcher initialized")

# Test 4: AI Processor
print("\n4. Testing AI Processor...")
from backend.ai_processor import get_ai_processor
ai = get_ai_processor()
print(f"   ✓ AI processor initialized")

# Test 5: File Organizer
print("\n5. Testing File Organizer...")
from backend.file_organizer import get_file_organizer
organizer = get_file_organizer()
print(f"   ✓ File organizer initialized")

# Test 6: Flask App
print("\n6. Testing Flask App...")
from web.app import create_app
app = create_app()
print(f"   ✓ Flask app created")

print("\n" + "="*50)
print("✅ ALL TESTS PASSED!")
print("="*50)
print("\nIntelly Jelly is ready to run!")
print("Start the app with: python main.py")
