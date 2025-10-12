#!/usr/bin/env python3
"""
Static verification of the procedure status implementation.
This script checks that all required components are in place without needing a running server.
"""

import os
import json
import sys
from pathlib import Path

def print_status(check_name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {check_name}")
    if details:
        print(f"   {details}")

def verify_file_exists(filepath, description):
    exists = os.path.exists(filepath)
    print_status(f"{description} exists", exists, filepath)
    return exists

def verify_function_in_file(filepath, function_name):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            found = function_name in content
            print_status(f"Function '{function_name}' found", found, filepath)
            return found
    except Exception as e:
        print_status(f"Check function '{function_name}'", False, str(e))
        return False

def verify_route_in_file(filepath, route_path, method="get"):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Check for route decorator
            route_found = f'@router.{method}("{route_path}")' in content
            print_status(f"Route {method.upper()} {route_path}", route_found, filepath)
            return route_found
    except Exception as e:
        print_status(f"Check route {method.upper()} {route_path}", False, str(e))
        return False

def verify_status_directory():
    status_dir = Path("app/data/user_status")
    exists = status_dir.exists() and status_dir.is_dir()
    print_status("Status directory exists", exists, str(status_dir))
    
    if exists:
        gitkeep = status_dir / ".gitkeep"
        gitkeep_exists = gitkeep.exists()
        print_status(".gitkeep file present", gitkeep_exists, str(gitkeep))
    
    return exists

def verify_imports():
    """Verify key imports are in place."""
    checks = [
        ("app/api/procedure.py", "from app.core.statemachine import UserStateMachine"),
        ("app/core/statemachine.py", "from app.services.status_service import save_user_status"),
    ]
    
    all_passed = True
    for filepath, import_line in checks:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                found = import_line in content
                print_status(f"Import in {filepath}", found, import_line)
                all_passed = all_passed and found
        except Exception as e:
            print_status(f"Check import in {filepath}", False, str(e))
            all_passed = False
    
    return all_passed

def verify_procedure_file():
    """Verify the pizza_custom procedure file is valid."""
    filepath = "app/data/procedures/pizza_custom.json"
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        required_fields = ["id", "name", "version", "steps"]
        all_present = all(field in data for field in required_fields)
        print_status("Procedure JSON structure", all_present, f"Has all required fields: {required_fields}")
        
        if all_present:
            step_count = len(data["steps"])
            print_status(f"Procedure has {step_count} steps", True, f"Steps: {[s['name'] for s in data['steps']]}")
        
        return all_present
    except Exception as e:
        print_status("Procedure JSON validation", False, str(e))
        return False

def main():
    print("=" * 60)
    print("Procedure Status Implementation - Static Verification")
    print("=" * 60)
    print()
    
    all_checks_passed = True
    
    # Check 1: Core Files Exist
    print("📁 Checking Core Files...")
    checks = [
        ("app/api/procedure.py", "API endpoint file"),
        ("app/services/status_service.py", "Status service file"),
        ("app/core/statemachine.py", "State machine file"),
        ("test_procedure_status.sh", "Test script"),
        ("TEST_PROCEDURE_STATUS.md", "Test documentation"),
    ]
    
    for filepath, description in checks:
        all_checks_passed = verify_file_exists(filepath, description) and all_checks_passed
    print()
    
    # Check 2: Status Directory
    print("📂 Checking Status Directory...")
    all_checks_passed = verify_status_directory() and all_checks_passed
    print()
    
    # Check 3: API Endpoint
    print("🌐 Checking API Endpoint...")
    all_checks_passed = verify_route_in_file("app/api/procedure.py", "/procedure", "get") and all_checks_passed
    all_checks_passed = verify_function_in_file("app/api/procedure.py", "get_procedure_status") and all_checks_passed
    print()
    
    # Check 4: Status Service Functions
    print("💾 Checking Status Service Functions...")
    functions = [
        "save_user_status",
        "load_user_status",
        "get_status_file_path",
        "ensure_status_directory",
    ]
    for func in functions:
        all_checks_passed = verify_function_in_file("app/services/status_service.py", func) and all_checks_passed
    print()
    
    # Check 5: State Machine Integration
    print("🔧 Checking State Machine Integration...")
    all_checks_passed = verify_function_in_file("app/core/statemachine.py", "get_procedure_status") and all_checks_passed
    all_checks_passed = verify_function_in_file("app/core/statemachine.py", "_save_status_file") and all_checks_passed
    print()
    
    # Check 6: Imports
    print("📦 Checking Imports...")
    all_checks_passed = verify_imports() and all_checks_passed
    print()
    
    # Check 7: Procedure Data
    print("📋 Checking Procedure Data...")
    all_checks_passed = verify_procedure_file() and all_checks_passed
    print()
    
    # Summary
    print("=" * 60)
    if all_checks_passed:
        print("✅ All Static Verification Checks PASSED")
        print()
        print("Implementation appears complete and correct.")
        print("Ready for live testing with running server.")
        print()
        print("Next steps:")
        print("1. Start server: uvicorn app.main:app --host 0.0.0.0 --port 8000")
        print("2. Run tests: bash test_procedure_status.sh")
        return 0
    else:
        print("❌ Some Verification Checks FAILED")
        print()
        print("Please review the failed checks above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())