#!/usr/bin/env python3
"""
Test script to verify that the fix for deleting old user status files works correctly.

This test verifies that when starting a new procedure, the old status file is deleted
and a new one is created with fresh state (step 1, no prior progress).
"""

import json
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Import the modules we need to test
try:
    from app.core.statemachine import UserStateMachine, procedure_from_json
    from app.services.status_service import get_status_file_path, load_user_status
except ImportError as e:
    logger.error(f"Failed to import required modules: {e}")
    sys.exit(1)


def load_procedure_json(procedure_id: str) -> dict:
    """Load a procedure JSON file."""
    procedure_file = Path(f"app/data/procedures/{procedure_id.split('@')[0]}.json")
    if not procedure_file.exists():
        raise FileNotFoundError(f"Procedure file not found: {procedure_file}")
    
    with open(procedure_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def create_old_status_file(username: str, procedure_id: str) -> Path:
    """Create a status file with existing progress to simulate an old session."""
    status_file = get_status_file_path(username, procedure_id)
    
    # Create a status file showing progress at step 3
    old_status = {
        "_comment": "OLD STATUS FILE - Should be deleted when starting new procedure",
        "username": username,
        "id": procedure_id,
        "name": "Make a Custom Pizza",
        "version": 1,
        "steps": [
            {"id": 1, "name": "Show pizza dough", "status": "done"},
            {"id": 2, "name": "Add lettuce", "status": "done"},
            {"id": 3, "name": "Add black olives", "status": "in_progress"},
            {"id": 4, "name": "Add red tomatoes", "status": "todo"},
            {"id": 5, "name": "Add multiple cheddar slices", "status": "todo"},
            {"id": 6, "name": "Add some Jalapeno peppers", "status": "todo"},
            {"id": 7, "name": "Add exactly 3 parts of pumpkin", "status": "todo"}
        ]
    }
    
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(old_status, f, indent=2)
    
    logger.info(f"✓ Created old status file: {status_file}")
    return status_file


def dummy_callbacks(*args, **kwargs):
    """Dummy callback functions for the state machine."""
    pass


def run_test():
    """Run the user status reset test."""
    print("\n" + "="*70)
    print("TEST: User Status File Reset on start_procedure()")
    print("="*70)
    
    username = "Miak"
    procedure_id = "pizza_custom@v1"
    
    try:
        # Step 1: Create old status file to simulate existing session
        print(f"\n[STEP 1] Creating old status file for user '{username}'...")
        status_file_path = create_old_status_file(username, procedure_id)
        
        # Verify old file exists
        if not status_file_path.exists():
            logger.error(f"✗ Failed to create old status file")
            return False
        
        # Load and verify old content
        with open(status_file_path, 'r') as f:
            old_content = json.load(f)
        
        print(f"  Old file exists: {status_file_path}")
        print(f"  Old status - Step 3 in_progress, Steps 1-2 done")
        
        # Step 2: Load the procedure definition
        print(f"\n[STEP 2] Loading procedure definition '{procedure_id}'...")
        procedure_json = load_procedure_json(procedure_id)
        procedure = procedure_from_json(procedure_json)
        logger.info(f"✓ Loaded procedure with {len(procedure.steps)} steps")
        
        # Step 3: Create state machine and start procedure
        print(f"\n[STEP 3] Starting new procedure (should delete old file)...")
        state_machine = UserStateMachine(
            on_step=dummy_callbacks,
            on_progress_step=dummy_callbacks,
            post_to_vlm=dummy_callbacks
        )
        
        # Start the procedure - this should trigger deletion of old file
        state_machine.start_procedure(username, procedure)
        logger.info(f"✓ start_procedure() called")
        
        # Give it a moment to complete file operations
        import time
        time.sleep(0.1)
        
        # Step 4: Verify the status file has been replaced with fresh content
        print(f"\n[STEP 4] Verifying status file was replaced with fresh state...")
        
        # Load the current status file
        if not status_file_path.exists():
            logger.error(f"✗ FAIL: Status file doesn't exist after start_procedure: {status_file_path}")
            return False
        
        with open(status_file_path, 'r') as f:
            current_content = json.load(f)
        
        # Check if the old content is gone (it had step 3 in_progress)
        if current_content == old_content:
            logger.error(f"✗ FAIL: Status file content unchanged - old status was not replaced")
            return False
        
        logger.info(f"✓ Status file content changed (old status was replaced)")
        
        # Step 5: Verify new file has fresh state
        print(f"\n[STEP 5] Verifying new status has fresh state...")
        
        # The state machine should have saved a new status file
        new_status = load_user_status(username, procedure_id)
        
        if not new_status:
            logger.error(f"✗ FAIL: No new status file was created")
            return False
        
        logger.info(f"✓ New status file created")
        
        # Step 6: Verify the new file has fresh state
        print(f"\n[STEP 6] Verifying new status has fresh state (step 1)...")
        
        # Check that we're starting from step 1
        steps = new_status.get("steps", [])
        if not steps:
            logger.error(f"✗ FAIL: No steps in new status file")
            return False
        
        # First step should be in_progress, rest should be todo
        first_step = steps[0]
        if first_step.get("status") != "in_progress":
            logger.error(f"✗ FAIL: First step status is '{first_step.get('status')}', expected 'in_progress'")
            return False
        
        logger.info(f"✓ Step 1 status: in_progress (correct)")
        
        # Check that previously completed steps are now 'todo'
        done_steps = [s for s in steps if s.get("status") == "done"]
        if done_steps:
            logger.error(f"✗ FAIL: Found {len(done_steps)} steps marked as 'done', expected 0")
            return False
        
        logger.info(f"✓ No steps marked as 'done' (correct)")
        
        # All other steps should be 'todo'
        todo_steps = [s for s in steps[1:] if s.get("status") == "todo"]
        if len(todo_steps) != len(steps) - 1:
            logger.error(f"✗ FAIL: Expected {len(steps)-1} 'todo' steps, found {len(todo_steps)}")
            return False
        
        logger.info(f"✓ Steps 2-7 status: todo (correct)")
        
        # Step 7: Display the new status
        print(f"\n[STEP 7] New status file content:")
        print(json.dumps(new_status, indent=2))
        
        # All tests passed!
        print("\n" + "="*70)
        print("*** ALL TESTS PASSED! ***")
        print("="*70)
        print("\nSummary:")
        print("  - Old status (step 3 in progress, steps 1-2 done) was replaced")
        print("  - New status file created with fresh state (step 1 in progress)")
        print("  - Step 1 is 'in_progress', all others are 'todo'")
        print("  - The fix in statemachine.py:168-171 works correctly!")
        print("="*70 + "\n")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ TEST FAILED WITH EXCEPTION: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = run_test()
    sys.exit(0 if success else 1)