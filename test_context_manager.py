#!/usr/bin/env python3
"""
Simple test script to verify the ContextManager get_environment() method works correctly.
"""

import sys
import os
import tempfile
import subprocess
from pathlib import Path

# Add the inference directory to the path so we can import utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'inference', 'make_datasets'))

try:
    from utils import ContextManager
    print("✓ Successfully imported ContextManager")
except ImportError as e:
    print(f"✗ Failed to import ContextManager: {e}")
    sys.exit(1)

def test_get_environment():
    """Test the get_environment method implementation."""
    print("\n=== Testing ContextManager.get_environment() ===")
    
    # Create a temporary git repository for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir) / "test_repo"
        repo_path.mkdir()
        
        # Initialize a git repository
        os.chdir(repo_path)
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], check=True, capture_output=True)
        
        # Create a dummy file and commit
        test_file = repo_path / "test.txt"
        test_file.write_text("test content")
        subprocess.run(["git", "add", "test.txt"], check=True, capture_output=True)
        result = subprocess.run(["git", "commit", "-m", "Initial commit"], check=True, capture_output=True)
        
        # Get the commit hash
        commit_result = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
        commit_hash = commit_result.stdout.strip()
        
        print(f"✓ Created test repository at {repo_path}")
        print(f"✓ Initial commit: {commit_hash}")
        
        # Test the ContextManager
        try:
            with ContextManager(str(repo_path), commit_hash, verbose=False) as cm:
                env_info = cm.get_environment()
                
                print("✓ Successfully called get_environment()")
                print(f"✓ Returned type: {type(env_info)}")
                
                # Verify expected keys are present
                expected_keys = [
                    "python_version", "python_executable", "platform", 
                    "system", "architecture", "machine", "processor",
                    "repo_path", "base_commit", "working_directory"
                ]
                
                missing_keys = []
                for key in expected_keys:
                    if key not in env_info:
                        missing_keys.append(key)
                
                if missing_keys:
                    print(f"✗ Missing expected keys: {missing_keys}")
                    return False
                else:
                    print("✓ All expected keys present in environment info")
                
                # Print some key information
                print(f"  - Python version: {env_info['python_version'].split()[0]}")
                print(f"  - Platform: {env_info['platform']}")
                print(f"  - System: {env_info['system']}")
                print(f"  - Repo path: {env_info['repo_path']}")
                print(f"  - Base commit: {env_info['base_commit']}")
                
                # Check if conda info was detected
                if "conda_environment" in env_info:
                    print(f"  - Conda environment: {env_info['conda_environment']}")
                if "conda_info" in env_info:
                    print("  - Conda info detected")
                else:
                    print("  - No conda environment detected (this is normal)")
                
                return True
                
        except Exception as e:
            print(f"✗ Error testing ContextManager: {e}")
            return False

def main():
    """Run the test."""
    print("Testing ContextManager get_environment() implementation...")
    
    success = test_get_environment()
    
    if success:
        print("\n✓ All tests passed! The get_environment() method is working correctly.")
        return 0
    else:
        print("\n✗ Tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
