#!/usr/bin/env python3
"""
Test script for Ollama integration
Run this to verify Ollama connectivity and model fetching
"""

import requests
import sys

def test_ollama_connection(base_url="http://localhost:11434"):
    """Test connection to Ollama server"""
    print(f"Testing connection to Ollama at {base_url}...")
    
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        
        data = response.json()
        models = data.get('models', [])
        
        if not models:
            print("❌ No models found on Ollama server")
            print("Please run: ollama pull llama3.2")
            return False
        
        print(f"✅ Connected successfully!")
        print(f"Found {len(models)} model(s):")
        for model in models:
            name = model.get('name', 'Unknown')
            size = model.get('size', 0) / (1024**3)  # Convert to GB
            print(f"  - {name} ({size:.2f} GB)")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Ollama server at {base_url}")
        print("Make sure Ollama is running:")
        print("  1. Install Ollama from https://ollama.ai/download")
        print("  2. Start Ollama (it runs automatically after install)")
        print("  3. Verify with: ollama list")
        return False
        
    except requests.exceptions.Timeout:
        print(f"❌ Connection to {base_url} timed out")
        return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_ollama_generate(base_url="http://localhost:11434", model="llama3.2"):
    """Test Ollama generation with a simple prompt"""
    print(f"\nTesting generation with model: {model}...")
    
    prompt = """Suggest improved file names for the following files. Return JSON array with original_path, suggested_name, and confidence (0-100).

Files to process:
- The.Walking.Dead.S01E01.720p.mkv
"""
    
    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 500
                }
            },
            timeout=60
        )
        response.raise_for_status()
        
        data = response.json()
        text = data.get('response', '')
        
        print(f"✅ Generation successful!")
        print(f"Response length: {len(text)} characters")
        print(f"Response preview:\n{text[:200]}...")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot connect to Ollama server")
        return False
        
    except requests.exceptions.Timeout:
        print(f"❌ Generation timed out (model may be downloading or hardware is slow)")
        return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434"
    
    print("=" * 60)
    print("Ollama Integration Test")
    print("=" * 60)
    
    # Test connection and model listing
    if not test_ollama_connection(base_url):
        sys.exit(1)
    
    # Test generation (optional, can be slow)
    print("\nWould you like to test AI generation? (this may take a while)")
    print("Press Enter to skip, or type the model name to test:")
    
    user_input = input("> ").strip()
    if user_input:
        model = user_input if user_input else "llama3.2"
        test_ollama_generate(base_url, model)
    else:
        print("Skipping generation test.")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)
