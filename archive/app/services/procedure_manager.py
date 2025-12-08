import asyncio
import logging
import time
from time import perf_counter
from typing import Dict, Optional, List
from app.domain.models import UserSession, ProcedureDef, Decision
from app.domain.procedure_engine import ProcedureEngine
from app.domain.events import (
    DomainEvent, StepStarted, StepProgressed, ProcedureCompleted,
    VLMDispatchNeeded, FeedbackNeeded, StatusChanged
)
from app.services.vlm_service import VLMService
from app.services.feedback_service import FeedbackService
from app.services.status_service import save_user_status, delete_all_user_status
from app.services.rule_validation import RuleValidationService
from app.services.context_analysis import ContextAnalysisService
from app.core.frame_store import get_frame, clear_frame
from app.core.metrics import get_metrics_collector, TimingMetrics
from app.config import settings

logger = logging.getLogger(__name__)

class ProcedureManager:
    def __init__(self):
        self.engine = ProcedureEngine()
        self.sessions: Dict[str, UserSession] = {}
        self.vlm_service = VLMService()
        self.feedback_service = FeedbackService()
        self.rule_validation = RuleValidationService()
        self.context_analysis = ContextAnalysisService()

    def _get_or_create_session(self, username: str) -> UserSession:
        if username not in self.sessions:
            self.sessions[username] = UserSession(username=username)
        return self.sessions[username]

    def _process_events(self, events: List[DomainEvent]):
        for event in events:
            if isinstance(event, VLMDispatchNeeded):
                asyncio.create_task(self._dispatch_vlm(event))
            elif isinstance(event, StepStarted):
                asyncio.create_task(self.feedback_service.send_step_notification(
                    event.username, event.step_name
                ))
            elif isinstance(event, StepProgressed):
                asyncio.create_task(self.feedback_service.send_progress_notification(
                    event.username, event.from_step, event.to_step
                ))
            elif isinstance(event, FeedbackNeeded):
                asyncio.create_task(self.feedback_service.send_feedback(
                    event.username, event.message
                ))
            elif isinstance(event, StatusChanged):
                self._save_status(event.username)
            elif isinstance(event, ProcedureCompleted):
                pass # Handled by StepProgressed(to_step=-1) usually, or we can add specific logic

    def _save_status(self, username: str):
        session = self.sessions.get(username)
        if session and session.procedure:
            try:
                status_data = self.get_procedure_status(username)
                if status_data:
                    save_user_status(username, status_data)
            except Exception as e:
                logger.error(f"Failed to save status: {e}")

    async def _dispatch_vlm(self, event: VLMDispatchNeeded):
        username = event.username
        frame_id = event.frame_id
        
        # [TIMING] Record callback start time
        callback_start = perf_counter()
        logger.info(f"[⏱️ TIMING] VLM dispatch started - username={username}, frame_id={frame_id}")
        
        try:
            # [TIMING] Retrieve frame bytes from storage
            frame_retrieve_start = perf_counter()
            frame_bytes = get_frame(frame_id)
            frame_retrieve_ms = (perf_counter() - frame_retrieve_start) * 1000
            
            if not frame_bytes:
                logger.error(f"Frame {frame_id} not found for user {username}")
                return
            
            logger.info(f"[⏱️ TIMING] Frame retrieval completed - duration={frame_retrieve_ms:.3f}ms")

            # [TIMING] Request preparation
            request_prep_start = perf_counter()
            step_def = event.step_def
            question = step_def["positives"][0]
            negatives = step_def["negatives"]
            bounding_questions = step_def.get("bounding_questions", [])
            request_prep_ms = (perf_counter() - request_prep_start) * 1000
            logger.info(f"[⏱️ TIMING] Request preparation completed - duration={request_prep_ms:.3f}ms")
            
            # [TIMING] Send to VLM
            vlm_request_start = perf_counter()
            response_json, http_post_ms, server_proc_ms = await self.vlm_service.query(
                file_bytes=frame_bytes,
                question=question,
                negatives=negatives,
                bounding_questions=bounding_questions,
                debug=event.debug
            )
            vlm_request_ms = (perf_counter() - vlm_request_start) * 1000
            logger.info(f"[⏱️ TIMING] Total VLM request time - duration={vlm_request_ms:.2f}ms")
            
            # [TIMING] Parse response
            response_parse_start = perf_counter()
            decision = self._parse_vlm_response(response_json)
            response_parse_ms = (perf_counter() - response_parse_start) * 1000
            logger.info(f"[⏱️ TIMING] Response parsing completed - duration={response_parse_ms:.3f}ms")
            
            # [TIMING] State machine update
            state_machine_start = perf_counter()
            await self.handle_vlm_decision(username, frame_id, decision, response_json)
            state_machine_ms = (perf_counter() - state_machine_start) * 1000
            logger.info(f"[⏱️ TIMING] State machine decision processing - duration={state_machine_ms:.3f}ms")
            
            # [TIMING] Clear frame
            frame_clear_start = perf_counter()
            clear_frame(frame_id)
            frame_clear_ms = (perf_counter() - frame_clear_start) * 1000
            logger.info(f"[⏱️ TIMING] Frame cleared - duration={frame_clear_ms:.3f}ms")
            
            # [TIMING] Total duration
            callback_end = perf_counter()
            callback_duration = (callback_end - callback_start) * 1000
            
            # Log breakdown
            logger.info(f"[⏱️ TIMING] ========== DISPATCH BREAKDOWN ==========")
            logger.info(f"[⏱️ TIMING] Frame Retrieval:      {frame_retrieve_ms:7.2f}ms")
            logger.info(f"[⏱️ TIMING] Request Preparation:  {request_prep_ms:7.2f}ms")
            logger.info(f"[⏱️ TIMING] HTTP POST (total):    {http_post_ms:7.2f}ms")
            if server_proc_ms is not None:
                logger.info(f"[⏱️ TIMING]   └─ VLM Processing:  {server_proc_ms:7.2f}ms")
            logger.info(f"[⏱️ TIMING] Response Parsing:     {response_parse_ms:7.2f}ms")
            logger.info(f"[⏱️ TIMING] State Machine Update: {state_machine_ms:7.2f}ms")
            logger.info(f"[⏱️ TIMING] TOTAL DISPATCH:       {callback_duration:7.2f}ms")
            logger.info(f"[⏱️ TIMING] ========================================")
            
            # [METRICS] Record metrics
            try:
                from app.core.vlm_worker import _frame_queue_timings
                queue_wait_ms = _frame_queue_timings.pop(frame_id, None)
                
                metrics = TimingMetrics(
                    queue_wait_ms=queue_wait_ms,
                    http_post_ms=http_post_ms,
                    server_proc_ms=server_proc_ms,
                    total_ms=callback_duration
                )
                
                metrics_collector = get_metrics_collector()
                metrics_collector.record_timing(username, metrics)
                metrics_collector.log_metrics(metrics, username)
                
            except Exception as e:
                logger.error(f"[METRICS] Failed to record metrics: {e}", exc_info=True)
            
        except Exception as e:
            logger.error(f"VLM dispatch failed: {e}", exc_info=True)

    def _parse_vlm_response(self, response: Dict) -> Decision:
        data = response.get("data") or response
        final = data.get("final")
        result = data.get("result")
        
        val = final if final is not None else result
        
        if not val:
            return Decision.NO
            
        s = str(val).lower().strip()
        if s in ("yes", "true", "1"):
            return Decision.YES
        return Decision.NO

    # Public API methods

    def start_procedure(self, username: str, procedure: ProcedureDef):
        delete_all_user_status(username)
        session = self._get_or_create_session(username)
        events = self.engine.start_procedure(session, procedure, int(time.time() * 1000))
        self._process_events(events)

    def pause(self, username: str):
        session = self.sessions.get(username)
        if session:
            events = self.engine.pause(session)
            self._process_events(events)

    def resume(self, username: str):
        session = self.sessions.get(username)
        if session:
            events = self.engine.resume(session, int(time.time() * 1000))
            self._process_events(events)

    def abort(self, username: str):
        session = self.sessions.get(username)
        if session:
            events = self.engine.abort(session)
            self._process_events(events)

    def ingest_frame(self, username: str, frame_id: str):
        session = self.sessions.get(username)
        if session:
            events = self.engine.ingest_frame(session, frame_id, int(time.time() * 1000))
            self._process_events(events)

    async def handle_vlm_decision(self, username: str, frame_id: str, decision: Decision, vlm_response: Dict):
        session = self.sessions.get(username)
        if session:
            events = self.engine.handle_vlm_decision(
                session, frame_id, decision, vlm_response,
                self.rule_validation, self.context_analysis,
                int(time.time() * 1000)
            )
            self._process_events(events)

    def tick(self, username: str):
        session = self.sessions.get(username)
        if session:
            events = self.engine.tick(session, int(time.time() * 1000))
            self._process_events(events)
            
    def tick_all_users(self):
        """Tick all active sessions."""
        for username in list(self.sessions.keys()):
            try:
                self.tick(username)
            except Exception as e:
                logger.error(f"Error ticking user {username}: {e}", exc_info=True)

    def get_status(self, username: str) -> Dict:
        session = self.sessions.get(username)
        if not session:
            return {"username": username, "state": "IDLE"}
        
        step = self.engine._current_step_def(session)
        return {
            "username": username,
            "state": session.state.value,
            "procedure_id": session.procedure.id if session.procedure else None,
            "current_step_id": step.id if step else None,
            "current_step_name": step.name if step else None,
            "yes_consecutive": session.step_rt.yes_consecutive if session.step_rt else 0,
            "inflight": session.inflight,
            "has_buffered_frame": session.buffered_frame is not None,
        }

    def get_procedure_status(self, username: str) -> Optional[Dict]:
        session = self.sessions.get(username)
        if not session or not session.procedure:
            return None
            
        steps_with_status = []
        for idx, step in enumerate(session.procedure.steps):
            if session.state.value == "COMPLETED":
                 status = "done"
            elif idx < session.current_index:
                status = "done"
            elif idx == session.current_index and session.state.value == "WORKING":
                status = "in_progress"
            else:
                status = "todo"
            
            steps_with_status.append({
                "id": step.id,
                "name": step.name,
                "status": status
            })
            
        return {
            "username": username,
            "id": session.procedure.id,
            "name": session.procedure.name,
            "version": session.procedure.version,
            "steps": steps_with_status
        }
