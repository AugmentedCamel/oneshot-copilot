"""Procedure models and loading utilities."""
import json
import logging
from typing import Dict
from app.domain.models import ProcedureDef, StepDef, ReasoningConfig, CouncilMember, CouncilConfig
from app.models.rules import RuleDef

logger = logging.getLogger(__name__)

__all__ = ["ProcedureDef", "StepDef", "load_procedure"]


def procedure_from_json(j: Dict) -> ProcedureDef:
    logger.debug(f"[PROCEDURE_PARSE] Starting to parse procedure JSON - id={j.get('id')}")
    steps = []
    for st in j["steps"]:
        # Check if negatives field exists
        has_negatives = "negatives" in st
        negatives_value = st.get("negatives", [])
        
        # Check if bounding_questions field exists
        has_bounding = "bounding_questions" in st
        bounding_value = st.get("bounding_questions", [])
        
        # Check if debug field exists
        has_debug = "debug" in st
        debug_value = st.get("debug", False)
        
        # Parse rules if they exist
        rules_list = []
        if "rules" in st:
            rules_data = st["rules"]
            for rule_data in rules_data:
                # Support both "type" (JSON format) and "rule_type" (internal format) field names
                rule_type_value = rule_data.get("type") or rule_data.get("rule_type")
                if not rule_type_value:
                    logger.error(f"[PROCEDURE_PARSE] Missing rule type field in rule: {rule_data.get('name', 'unnamed')}")
                    raise KeyError("Rule definition must have 'type' or 'rule_type' field")
                
                # Support both "parameters" (JSON format) and "params" (internal format) field names
                params_value = rule_data.get("parameters") or rule_data.get("params", {})
                
                # Create RuleDef with defaults and let __post_init__ handle conversions
                rule = RuleDef(
                    rule_type=rule_type_value,
                    name=rule_data["name"],
                    enabled=rule_data.get("enabled", True),
                    failure_behavior=rule_data.get("failure_behavior", "block"),
                    params=params_value
                )
                rules_list.append(rule)
        
        # Parse step_context if it exists (for ai_node integration)
        reasoning_config = None
        if "step_context" in st:
            rc = st["step_context"]
            
            # Parse council if present
            council_config = None
            if "council" in rc:
                council_data = rc["council"]
                members = []
                for m in council_data.get("members", []):
                    members.append(CouncilMember(
                        role=m["role"],
                        prompt=m["prompt"],
                        attention=m.get("attention", "PRIMARY"),
                        weight=m.get("weight", 1.0)
                    ))
                council_config = CouncilConfig(
                    members=members,
                    reasoning_rules=council_data.get("reasoning_rules", {})
                )
            
            reasoning_config = ReasoningConfig(
                step_id=rc.get("step_id", str(st["id"])),
                instruction=rc.get("instruction", ""),
                council=council_config
            )
            logger.debug(f"[PROCEDURE_PARSE] Parsed step_context for step {st['id']}")
        
        steps.append(StepDef(
            id=st["id"],
            name=st["name"],
            timeout_s=st["timeout_s"],
            debounce_consecutive_yes=st["debounce"]["consecutive_yes"],
            positives=st.get("positives", []),  # Optional for council-based procedures
            negatives=negatives_value,
            bounding_questions=bounding_value,
            debug=debug_value,
            rules=rules_list,
            step_context=reasoning_config,
        ))
    logger.info(f"[PROCEDURE_PARSE] Successfully parsed {len(steps)} steps from JSON")
    return ProcedureDef(
        id=j["id"],
        name=j["name"],
        version=j["version"],
        steps=steps,
    )


def load_procedure(file_path: str) -> ProcedureDef:
    """
    Load a procedure from a JSON file.
    
    Args:
        file_path: Path to the JSON file
        
    Returns:
        ProcedureDef object
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return procedure_from_json(data)