"""Procedure models and loading utilities."""
import json
from typing import Dict
from app.core.statemachine import ProcedureDef, StepDef, procedure_from_json

__all__ = ["ProcedureDef", "StepDef", "load_procedure"]


def load_procedure(file_path: str) -> ProcedureDef:
    """
    Load a procedure from a JSON file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        ProcedureDef object
    """
    with open(file_path, 'r') as f:
        data = json.load(f)
    return procedure_from_json(data)