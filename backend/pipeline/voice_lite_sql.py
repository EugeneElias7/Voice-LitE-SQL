"""Voice-LitE-SQL -- Level 9: Full end-to-end voice-to-SQL pipeline orchestration.

Combines L5 (ASR), L6 (normalization), L7 (retrieval), L8.1 (NLP),
L4 (execution), and L8 (correction) into a unified pipeline.
"""

import time
import hashlib
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from backend.asr.whisper_engine import WhisperEngine, ASRError
from backend.phonetics import DatabaseAwareNormalizer, DatabaseVocabulary
from backend.nlp import (
    classify_intent,
    link_schema_entities,
    match_phrases,
)
from backend.retrieval import (
    SchemaRetriever,
    SentenceTransformerEmbedder,
    CountVectorEmbedder,
    format_schema_context,
    EmbeddingError,
)
from backend.retrieval.embeddings import EMBEDDING_DIMENSIONS
from backend.retrieval.reranker import RerankWeights, rerank_retrieval
from backend.retrieval.relationship_filter import filter_relationships
from backend.validation import validate_sql_structure
from backend.llm.sql_generator import extract_sql, validate_read_only
from backend.database.executor import execute_sql, ExecutionResult
from backend.correction import SQLCorrector, build_correction_context_text
from backend.evaluation.evaluator import results_equal
from backend.config import (  # noqa: E402
    DEFAULT_DB_PATH as DEFAULT_DB,
    get_index_dir,
    LLM_MODEL as DEFAULT_MODEL,
    LLM_PROVIDER,
    LLM_TIMEOUT,
    PIPELINE_MAX_CORRECTION_ATTEMPTS as MAX_CORRECTION_ATTEMPTS,
    PIPELINE_CORRECTION_TIMEOUT as CORRECTION_TIMEOUT,
)
from backend.llm.unified_client import LLMError, generate, probe_llm
from backend.pipeline.pipeline_result import (
    PipelineResult,
    PipelineTimer,
    AudioStage,
    ASRStage,
    NormalizationStage,
    NLPStage,
    RetrievalStage,
    GenerationStage,
    ValidationStage,
    ExecutionStage,
    CorrectionStage,
)

DEFAULT_INDEX_DIR = get_index_dir()


def split_multiple_questions(text: str) -> List[str]:
    """
    Split a text containing multiple questions into individual questions.
    Handles common patterns like:
    - Questions separated by ? followed by capital letter
    - Questions separated by ; or newline
    - Questions with "and" conjunctions that indicate separate queries
    """
    text = text.strip()
    if not text:
        return []
    
    # First, try to split by question marks followed by whitespace and capital letter
    # This handles: "Question one? Question two? Question three?"
    parts = re.split(r'\?\s+(?=[A-Z])', text)
    
    # If that didn't split, try other delimiters
    if len(parts) == 1:
        # Try splitting by semicolons
        parts = re.split(r';\s*', text)
    
    # If still single part, try splitting by newlines
    if len(parts) == 1:
        parts = re.split(r'\n\s*', text)
    
    # If still single part, try splitting by period followed by space and capital letter
    if len(parts) == 1:
        parts = re.split(r'\.\s+(?=[A-Z])', text)
    
    # If still single part, try "and" as conjunction for separate questions
    # Only split on " and " when it seems to connect two questions
    if len(parts) == 1:
        # Look for patterns like "question one? and question two?"
        and_parts = re.split(r'\s+and\s+(?=[A-Z][a-z]+\s)', text)
        if len(and_parts) > 1:
            parts = and_parts
    
    # Clean up each part
    questions = []
    for part in parts:
        part = part.strip()
        # Remove trailing punctuation that might be left over
        part = part.rstrip('.;,').strip()
        # Ensure it ends with a question mark
        if part and not part.endswith('?'):
            part += '?'
        if part and len(part) > 3:  # Minimum reasonable question length
            questions.append(part)
    
    # If splitting produced only one question, return as-is
    if len(questions) <= 1:
        return [text.strip()]
    
    return questions


@dataclass
class PipelineConfig:
    """Configuration for the Voice-LitE-SQL pipeline."""
    db_path: str = str(DEFAULT_DB)
    index_dir: str = str(DEFAULT_INDEX_DIR)
    embedding_model: str = "all-MiniLM-L6-v2"
    asr_model: str = "small"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_backend: str = "auto"
    asr_language: Optional[str] = None
    llm_model: str = DEFAULT_MODEL
    top_k: int = 5
    max_correction_attempts: int = 3
    correction_timeout: int = 120
    fake_embedder: bool = False
    enable_nlp: bool = True
    enable_correction: bool = True
    enable_validation: bool = True


class VoiceLitESQLPipeline:
    """End-to-end voice-to-SQL pipeline orchestrator."""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self._retriever: Optional[SchemaRetriever] = None
        self._whisper: Optional[WhisperEngine] = None
        self._normalizer: Optional[DatabaseAwareNormalizer] = None
        self._vocabulary: Optional[DatabaseVocabulary] = None

    def _init_retriever(self):
        """Initialize or reuse the schema retriever."""
        if self._retriever is None:
            if self.config.fake_embedder:
                embedder = CountVectorEmbedder(dimensions=384)
            else:
                try:
                    embedder = SentenceTransformerEmbedder(model_name=self.config.embedding_model)
                except EmbeddingError as exc:
                    raise RuntimeError(f"Embedding model unavailable: {exc}")

            self._retriever = SchemaRetriever(
                db_path=self.config.db_path,
                persist_dir=self.config.index_dir,
                embedding_model=self.config.embedding_model,
                embedding_dimensions=EMBEDDING_DIMENSIONS.get(self.config.embedding_model, 384),
                top_k=self.config.top_k,
                embedder=embedder,
            )
            self._retriever.build_index()

    def _init_asr(self):
        """Initialize the ASR engine."""
        if self._whisper is None:
            self._whisper = WhisperEngine(
                model_name=self.config.asr_model,
                device=self.config.asr_device,
                compute_type=self.config.asr_compute_type,
                language=self.config.asr_language,
                backend=self.config.asr_backend,
            )

    def _init_normalizer(self):
        """Initialize the L6 phonetic normalizer."""
        if self._normalizer is None:
            self._vocabulary = DatabaseVocabulary.from_database(self.config.db_path)
            self._normalizer = DatabaseAwareNormalizer(self._vocabulary)

    def run_text_query(self, question: str, question_id: Optional[str] = None,
                       category: Optional[str] = None, reference_sql: Optional[str] = None) -> PipelineResult:
        """Process a text question through the complete pipeline (stages 3-10)."""
        result = PipelineResult(
            question_id=question_id or "",
            category=category or "",
            reference_sql=reference_sql or "",
        )

        # Stage 3: L6 Normalization (optional - for text input, minimal effect)
        with PipelineTimer(result, "normalization"):
            result.normalization = self._run_normalization(question)

        normalized_text = result.normalization.normalized_text if result.normalization else question

        # Stage 4: L8.1 NLP Processing
        with PipelineTimer(result, "nlp"):
            result.nlp = self._run_nlp(normalized_text)

        # Stage 5: L7 Retrieval (optimized by L8.1)
        with PipelineTimer(result, "retrieval"):
            result.retrieval = self._run_retrieval(normalized_text, result.nlp)

        # Stage 6: Qwen SQL Generation
        with PipelineTimer(result, "generation"):
            result.generation = self._run_generation(normalized_text, result.retrieval)

        # Stage 7: SQL Structural Validation
        if self.config.enable_validation:
            with PipelineTimer(result, "validation"):
                result.validation = self._run_validation(result.generation.generated_sql, result.nlp)

        # Stage 8: L4 Execution
        with PipelineTimer(result, "execution"):
            result.execution = self._run_execution(result.generation.generated_sql)

        # Stage 9: L8 Execution-Guided Correction
        # Run correction if: execution failed, validation failed, OR we have reference SQL to verify correctness
        should_correct = (
            self.config.enable_correction and (
                not (result.execution and result.execution.success) or
                not (result.validation and result.validation.is_valid) or
                (result.reference_sql and result.execution and result.execution.success)
            )
        )
        if should_correct:
            with PipelineTimer(result, "correction"):
                result.correction = self._run_correction(
                    normalized_text,
                    result.generation.generated_sql,
                    result.retrieval,
                    result.nlp,
                    reference_sql=result.reference_sql,
                )

        # Stage 10: Final Result
        self._finalize_result(result)
        return result

    def run_text_query(self, question: str, question_id: Optional[str] = None,
                       category: Optional[str] = None, reference_sql: Optional[str] = None) -> PipelineResult:
        """Process a text question through the complete pipeline (stages 3-10).
        
        Handles multiple questions by splitting them and processing each individually.
        """
        # Check if input contains multiple questions
        questions = split_multiple_questions(question)
        
        if len(questions) <= 1:
            # Single question - use existing logic
            return self._run_single_text_query(question, question_id, category, reference_sql)
        
        # Multiple questions - process each and combine results
        return self._run_multi_question_query(questions, question_id, category, reference_sql)

    def _run_single_text_query(self, question: str, question_id: Optional[str] = None,
                               category: Optional[str] = None, reference_sql: Optional[str] = None) -> PipelineResult:
        """Process a single text question through the complete pipeline (stages 3-10)."""
        result = PipelineResult(
            question_id=question_id or "",
            category=category or "",
            reference_sql=reference_sql or "",
        )

        # Stage 3: L6 Normalization (optional - for text input, minimal effect)
        with PipelineTimer(result, "normalization"):
            result.normalization = self._run_normalization(question)

        normalized_text = result.normalization.normalized_text if result.normalization else question

        # Stage 4: L8.1 NLP Processing
        with PipelineTimer(result, "nlp"):
            result.nlp = self._run_nlp(normalized_text)

        # Stage 5: L7 Retrieval (optimized by L8.1)
        with PipelineTimer(result, "retrieval"):
            result.retrieval = self._run_retrieval(normalized_text, result.nlp)

        # Stage 6: Qwen SQL Generation
        with PipelineTimer(result, "generation"):
            result.generation = self._run_generation(normalized_text, result.retrieval)

        # Stage 7: SQL Structural Validation
        if self.config.enable_validation:
            with PipelineTimer(result, "validation"):
                result.validation = self._run_validation(result.generation.generated_sql, result.nlp)

        # Stage 8: L4 Execution
        with PipelineTimer(result, "execution"):
            result.execution = self._run_execution(result.generation.generated_sql)

        # Stage 9: L8 Execution-Guided Correction
        # Run correction if: execution failed, validation failed, OR we have reference SQL to verify correctness
        should_correct = (
            self.config.enable_correction and (
                not (result.execution and result.execution.success) or
                not (result.validation and result.validation.is_valid) or
                (result.reference_sql and result.execution and result.execution.success)
            )
        )
        if should_correct:
            with PipelineTimer(result, "correction"):
                result.correction = self._run_correction(
                    normalized_text,
                    result.generation.generated_sql,
                    result.retrieval,
                    result.nlp,
                    reference_sql=result.reference_sql,
                )

        # Stage 10: Final Result
        self._finalize_result(result)
        return result

    def _run_multi_question_query(self, questions: List[str], question_id: Optional[str] = None,
                                  category: Optional[str] = None, reference_sql: Optional[str] = None) -> PipelineResult:
        """Process multiple questions and combine results."""
        # Process each question individually
        sub_results = []
        for i, q in enumerate(questions):
            sub_id = f"{question_id}_part{i+1}" if question_id else f"multi_part{i+1}"
            sub_result = self._run_single_text_query(q, sub_id, category, None)
            sub_results.append(sub_result)
        
        # Combine results
        combined = PipelineResult(
            question_id=question_id or "multi_question",
            category=category or "multi_question",
            reference_sql=reference_sql or "",
        )
        
        # Combine stage results - use the first sub-result as base for non-accumulative stages
        first = sub_results[0]
        combined.audio = first.audio
        combined.asr = first.asr
        combined.normalization = first.normalization
        combined.nlp = first.nlp
        combined.retrieval = first.retrieval
        combined.generation = first.generation
        combined.validation = first.validation
        combined.execution = first.execution
        combined.correction = first.correction
        
        # Combine final results - concatenate SQLs and rows
        combined_sqls = []
        combined_rows = []
        all_correct = True
        for sr in sub_results:
            if sr.final_sql:
                combined_sqls.append(sr.final_sql)
            if sr.final_result_rows:
                combined_rows.extend(sr.final_result_rows)
            if not sr.final_correct:
                all_correct = False
        
        combined.final_sql = ";\n".join(combined_sqls) if combined_sqls else None
        combined.final_result_rows = combined_rows
        combined.final_correct = all_correct
        combined.final_status = "success" if all_correct else "partial"
        
        # Combine latencies
        combined_latencies = {}
        total_latency = 0.0
        for sr in sub_results:
            for stage, latency in sr.stage_latencies.items():
                if stage not in combined_latencies:
                    combined_latencies[stage] = 0.0
                combined_latencies[stage] += latency
            total_latency += sr.total_latency_ms
        
        combined.stage_latencies = combined_latencies
        combined.total_latency_ms = total_latency
        
        return combined

    def run_voice_query(self, audio_path: str, question_id: Optional[str] = None,
                        category: Optional[str] = None, reference_sql: Optional[str] = None,
                        reference_transcript: Optional[str] = None) -> PipelineResult:
        """Process an audio file through the complete pipeline (stages 1-10)."""
        result = PipelineResult(
            question_id=question_id or "",
            category=category or "",
            reference_sql=reference_sql or "",
        )

        # Stage 1: Audio
        with PipelineTimer(result, "audio"):
            result.audio = self._run_audio(audio_path)

        # Stage 2: ASR
        with PipelineTimer(result, "asr"):
            result.asr = self._run_asr(audio_path, reference_transcript)

        # If ASR failed, return early
        if not result.asr or not result.asr.raw_transcript:
            result.final_status = "error"
            return result

        # Continue with text pipeline using ASR transcript
        text_result = self.run_text_query(
            result.asr.raw_transcript,
            question_id=question_id,
            category=category,
            reference_sql=reference_sql,
        )

        # Merge stage results
        result.normalization = text_result.normalization
        result.nlp = text_result.nlp
        result.retrieval = text_result.retrieval
        result.generation = text_result.generation
        result.validation = text_result.validation
        result.execution = text_result.execution
        result.correction = text_result.correction
        result.final_sql = text_result.final_sql
        result.final_result_rows = text_result.final_result_rows
        result.final_correct = text_result.final_correct
        result.final_status = text_result.final_status
        result.stage_latencies.update(text_result.stage_latencies)
        result.total_latency_ms = sum(result.stage_latencies.values())

        return result

    def _run_audio(self, audio_path: str) -> AudioStage:
        """Stage 1: Audio input validation."""
        path = Path(audio_path)
        return AudioStage(
            audio_path=str(path),
            duration_seconds=None,
            capture_status="loaded" if path.exists() else "not_found",
        )

    def _run_asr(self, audio_path: str, reference_transcript: Optional[str] = None) -> ASRStage:
        """Stage 2: ASR transcription."""
        self._init_asr()
        transcription = self._whisper.transcribe(audio_path)

        wer = None
        if reference_transcript and transcription.success:
            from backend.asr.models import compute_wer
            wer = compute_wer(reference_transcript, transcription.transcript)

        return ASRStage(
            raw_transcript=transcription.transcript,
            model_name=transcription.model_name,
            wer=wer,
            reference_transcript=reference_transcript,
            latency_ms=transcription.transcription_time_ms,
        )

    def _run_normalization(self, text: str) -> NormalizationStage:
        """Stage 3: L6 phonetic normalization."""
        self._init_normalizer()
        started = time.perf_counter()
        norm_result = self._normalizer.correct(text)
        latency_ms = (time.perf_counter() - started) * 1000.0

        token_decisions = []
        for decision in norm_result.decisions:
            token_decisions.append({
                "original": decision.original,
                "replacement": decision.replacement,
                "confidence": decision.confidence,
                "applied": decision.applied,
                "strategy": decision.strategy,
                "reason": decision.reason,
                "scores": decision.scores,
                "candidate": decision.candidate,
            })

        return NormalizationStage(
            original_text=text,
            normalized_text=norm_result.text,
            token_decisions=token_decisions,
            latency_ms=latency_ms,
        )

    def _run_nlp(self, text: str) -> NLPStage:
        """Stage 4: L8.1 NLP processing."""
        started = time.perf_counter()

        # 1. Intent classification
        intent = classify_intent(text)
        intent_dict = {
            "primary_intent": intent.primary_intent.value,
            "join_required": intent.join_required,
            "aggregation_required": intent.aggregation_required,
            "grouping_required": intent.grouping_required,
            "ordering_required": intent.ordering_required,
            "subquery_likely": intent.subquery_likely,
            "confidence": intent.confidence,
        }

        # 2. Schema/entity linking
        linked_entities = link_schema_entities(text, self.config.db_path)
        linked_dict = [
            {
                "entity_type": e.entity_type,
                "table": e.table,
                "column": e.column,
                "match_type": e.match_type,
                "matched_text": e.matched_text,
                "confidence": e.confidence,
            }
            for e in linked_entities
        ]

        # 3. Phrase matching
        phrase_matches = match_phrases(text, self.config.db_path)
        phrase_dict = [
            {
                "phrase": p.phrase,
                "entity_type": p.entity_type,
                "table": p.table,
                "column": p.column,
                "match_type": p.match_type,
                "score": p.score,
                "concept": p.concept,
            }
            for p in phrase_matches
        ]

        latency_ms = (time.perf_counter() - started) * 1000.0

        return NLPStage(
            intent=intent_dict,
            linked_entities=linked_dict,
            phrase_matches=phrase_dict,
            latency_ms=latency_ms,
        )

    def _run_retrieval(self, text: str, nlp_stage: NLPStage) -> RetrievalStage:
        """Stage 5: L7 retrieval with L8.1 optimizations."""
        self._init_retriever()

        started = time.perf_counter()

        if self.config.enable_nlp:
            # Full L8.1 retrieval pipeline
            intent_obj = type('Intent', (), {
                'primary_intent': type('Enum', (), {'value': nlp_stage.intent['primary_intent']})(),
                'join_required': nlp_stage.intent['join_required'],
                'aggregation_required': nlp_stage.intent['aggregation_required'],
                'grouping_required': nlp_stage.intent['grouping_required'],
                'ordering_required': nlp_stage.intent['ordering_required'],
                'subquery_likely': nlp_stage.intent['subquery_likely'],
                'confidence': nlp_stage.intent['confidence'],
            })()

            linked_entities = [
                type('LinkedEntity', (), e)() for e in nlp_stage.linked_entities
            ]

            phrase_matches = [
                type('PhraseMatch', (), p)() for p in nlp_stage.phrase_matches
            ]

            # Initial retrieval
            retrieval = self._retriever.retrieve(text, top_k=self.config.top_k)

            # Reranking
            retrieval = rerank_retrieval(text, retrieval, intent_obj, linked_entities, phrase_matches)
            nlp_stage.reranked = True

            # Relationship filtering
            filtered_retrieval, rel_assessments = filter_relationships(
                text, retrieval, intent_obj, linked_entities, self.config.db_path
            )
            retrieval = filtered_retrieval

            nlp_stage.relationship_decisions = [
                {
                    "source_table": a.fk_source_table,
                    "source_column": a.fk_source_column,
                    "target_table": a.fk_target_table,
                    "target_column": a.fk_target_column,
                    "required": a.required,
                    "reason": a.reason,
                    "confidence": a.confidence,
                }
                for a in rel_assessments
            ]
            nlp_stage.filtered_items_count = len(filtered_retrieval.items)

            items = [item.to_dict() for item in retrieval.items]
        else:
            # Basic L7 retrieval without L8.1 optimizations
            retrieval = self._retriever.retrieve(text, top_k=self.config.top_k)
            items = [item.to_dict() for item in retrieval.items]

        latency_ms = (time.perf_counter() - started) * 1000.0

        return RetrievalStage(
            query_text=text,
            retrieved_items=items,
            top_k=self.config.top_k,
            latency_ms=latency_ms,
        )

    def _run_generation(self, text: str, retrieval_stage: RetrievalStage) -> GenerationStage:
        """Stage 6: Qwen SQL generation."""
        started = time.perf_counter()

        # Build schema context from retrieved items
        from backend.retrieval import RetrievedItem
        items = []
        for item_dict in retrieval_stage.retrieved_items:
            items.append(RetrievedItem(**item_dict))

        from backend.retrieval.schema_retriever import RetrievalResult
        retrieval = RetrievalResult(
            question=text,
            top_k=retrieval_stage.top_k,
            items=items,
            schema_context_text=format_schema_context(items),
        )

        # Build L8.1 style prompt
        schema_context = format_schema_context(items)
        forbidden = "INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, ATTACH, DETACH, PRAGMA, REPLACE, TRUNCATE, VACUUM, GRANT, REVOKE"
        prompt = f"""You are a SQLite SQL generation assistant.

Generate a single SQLite query that answers the user's question.

Rules:
- Return ONLY the SQL statement, with no explanation.
- Use only the provided schema. Do not invent tables or columns.
- Use SELECT (or WITH) only. The following operations are strictly forbidden: {forbidden}.
- Use JOIN only when the schema relationships below require it.
- You may only reference the foreign key relationships listed below.

RETRIEVED SCHEMA
{schema_context}

QUESTION
{text}

SQL:"""

        try:
            raw_response, _ = generate(
                prompt,
                model=self.config.llm_model,
                provider=LLM_PROVIDER,
                timeout=60,
            )
            sql = extract_sql(raw_response)
            validate_read_only(sql)
        except (LLMError, ValueError) as exc:
            return GenerationStage(
                raw_response=str(exc),
                generated_sql="",
                prompt_length=len(prompt),
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

        latency_ms = (time.perf_counter() - started) * 1000.0

        return GenerationStage(
            raw_response=raw_response,
            generated_sql=sql,
            prompt_length=len(prompt),
            latency_ms=latency_ms,
        )

    def _run_validation(self, sql: str, nlp_stage: Optional[NLPStage]) -> ValidationStage:
        """Stage 7: SQL structural validation."""
        intent_obj = None
        if nlp_stage and nlp_stage.intent:
            intent_obj = type('Intent', (), {
                'primary_intent': type('Enum', (), {'value': nlp_stage.intent['primary_intent']})(),
                'join_required': nlp_stage.intent['join_required'],
                'aggregation_required': nlp_stage.intent['aggregation_required'],
                'grouping_required': nlp_stage.intent['grouping_required'],
                'ordering_required': nlp_stage.intent['ordering_required'],
                'subquery_likely': nlp_stage.intent['subquery_likely'],
                'confidence': nlp_stage.intent['confidence'],
            })()

        validation = validate_sql_structure(sql, self.config.db_path, intent_obj)

        return ValidationStage(
            is_valid=validation.is_valid,
            issues=[{"severity": i.severity, "code": i.code, "message": i.message, "location": i.location} for i in validation.issues],
            tables_used=validation.tables_used,
            columns_used=validation.columns_used,
            joins=validation.joins,
            has_aggregation=validation.has_aggregation,
            has_group_by=validation.has_group_by,
            latency_ms=0.0,
        )

    def _run_execution(self, sql: str) -> ExecutionStage:
        """Stage 8: L4 read-only execution."""
        started = time.perf_counter()
        exec_result = execute_sql(sql, self.config.db_path)
        latency_ms = (time.perf_counter() - started) * 1000.0

        return ExecutionStage(
            success=exec_result.success,
            rows=[dict(zip(exec_result.columns, row)) for row in exec_result.rows] if exec_result.columns and exec_result.rows else [],
            columns=exec_result.columns or [],
            error=exec_result.error,
            error_type=exec_result.error_type,
            execution_time_ms=exec_result.execution_time_ms,
            latency_ms=latency_ms,
        )

    def _run_correction(self, question: str, original_sql: str,
                        retrieval_stage: RetrievalStage,
                        nlp_stage: Optional[NLPStage],
                        reference_sql: Optional[str] = None) -> CorrectionStage:
        """Stage 9: L8 execution-guided correction."""
        # Rebuild retrieval object
        from backend.retrieval import RetrievedItem
        items = [RetrievedItem(**item_dict) for item_dict in retrieval_stage.retrieved_items]
        from backend.retrieval.schema_retriever import RetrievalResult
        retrieval = RetrievalResult(
            question=question,
            top_k=retrieval_stage.top_k,
            items=items,
            schema_context_text=format_schema_context(items),
        )

        # Build context text
        context_text = retrieval_stage.retrieved_items[0].get("text", "") if retrieval_stage.retrieved_items else ""
        if not context_text:
            context_text = build_correction_context_text(retrieval)

        # Determine if L7 was correct (for harm tracking)
        l7_correct = False
        if reference_sql:
            ref_result = execute_sql(reference_sql, self.config.db_path)
            orig_result = execute_sql(original_sql, self.config.db_path)
            if ref_result.success and orig_result.success:
                l7_correct = results_equal(reference_sql, ref_result, original_sql, orig_result)

        corrector = SQLCorrector(
            db_path=self.config.db_path,
            model=self.config.llm_model,
            max_attempts=self.config.max_correction_attempts,
            timeout=self.config.correction_timeout,
        )

        ref_result_text = ""
        if reference_sql:
            ref_result_text = corrector.build_reference_result_text(reference_sql, self.config.db_path)

        correction_result = corrector.correct(
            question=question,
            category=nlp_stage.intent.get("primary_intent", "") if nlp_stage else "",
            question_id="",
            reference_sql=reference_sql or "",
            original_sql=original_sql,
            retrieval=retrieval,
            schema_context_text=context_text,
            reference_result_text=ref_result_text,
            is_l7_correct=l7_correct,
        )

        attempts = []
        for a in correction_result.attempts:
            attempts.append({
                "attempt_number": a.attempt_number,
                "sql": a.sql,
                "execution_success": bool(a.execution_result.success) if a.execution_result else False,
                "execution_error": a.execution_error,
                "execution_error_type": a.execution_error_type,
                "execution_time_ms": a.execution_time_ms,
                "is_correct": a.is_correct,
            })

        return CorrectionStage(
            attempts=attempts,
            total_attempts=correction_result.total_attempts,
            rescued=correction_result.rescued,
            harmed=correction_result.harmed,
            final_correct=correction_result.final_correct,
        )

    def _finalize_result(self, result: PipelineResult):
        """Determine final result and status."""
        # Get the final SQL (corrected or original)
        if result.correction and result.correction.attempts:
            # Find the last successful attempt or the last attempt
            for attempt in reversed(result.correction.attempts):
                if attempt.get("is_correct"):
                    result.final_sql = attempt["sql"]
                    result.final_correct = True
                    break
            if not result.final_sql:
                result.final_sql = result.correction.attempts[-1]["sql"]
        else:
            result.final_sql = result.generation.generated_sql if result.generation else ""

        # Evaluate correctness if reference SQL provided
        if result.reference_sql and result.execution and result.execution.success:
            from backend.database.executor import execute_sql
            from backend.evaluation.evaluator import results_equal
            ref_result = execute_sql(result.reference_sql, self.config.db_path)
            gen_result = execute_sql(result.final_sql, self.config.db_path)
            if ref_result.success and gen_result.success:
                result.final_correct = results_equal(
                    result.reference_sql, ref_result, result.final_sql, gen_result
                )
        else:
            # No reference SQL provided - consider execution success as correctness
            if result.execution and result.execution.success:
                result.final_correct = True

        # Get final execution result
        if result.final_correct and result.execution:
            result.final_result_rows = result.execution.rows
            result.final_status = "success"
        elif result.execution and result.execution.success:
            result.final_result_rows = result.execution.rows
            result.final_status = "success" if result.final_correct else "partial"
        else:
            result.final_status = "error"


def run_text_query(question: str, db_path: str = str(DEFAULT_DB),
                   question_id: Optional[str] = None,
                   category: Optional[str] = None,
                   reference_sql: Optional[str] = None,
                   **kwargs) -> PipelineResult:
    """Convenience function to run a text query through the pipeline."""
    config = PipelineConfig(db_path=db_path, **kwargs)
    pipeline = VoiceLitESQLPipeline(config)
    return pipeline.run_text_query(question, question_id, category, reference_sql)


def run_voice_query(audio_path: str, db_path: str = str(DEFAULT_DB),
                    question_id: Optional[str] = None,
                    category: Optional[str] = None,
                    reference_sql: Optional[str] = None,
                    reference_transcript: Optional[str] = None,
                    **kwargs) -> PipelineResult:
    """Convenience function to run a voice query through the pipeline."""
    config = PipelineConfig(db_path=db_path, **kwargs)
    pipeline = VoiceLitESQLPipeline(config)
    return pipeline.run_voice_query(audio_path, question_id, category, reference_sql, reference_transcript)