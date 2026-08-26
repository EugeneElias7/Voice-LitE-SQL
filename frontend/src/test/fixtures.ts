import type {
  DemoQuestion,
  PipelineResult,
  SchemaPayload,
  StreamEvent,
  SystemStatus,
} from '../types'

export const demoQuestions: DemoQuestion[] = [
  { question: 'How many employees are there?', category: 'aggregate' },
  { question: 'Which department has the highest average salary?', category: 'complex' },
  { question: 'List the most expensive products first.', category: 'ORDER BY' },
]

export const schemaPayload: SchemaPayload = {
  database: 'enterprise',
  path: 'backend/data/enterprise.db',
  tables: [
    {
      name: 'employees',
      columns: [
        { name: 'employee_id', data_type: 'INTEGER', not_null: true, default_value: null, primary_key_position: 1 },
        { name: 'employee_name', data_type: 'TEXT', not_null: true, default_value: null, primary_key_position: 0 },
        { name: 'department_id', data_type: 'INTEGER', not_null: false, default_value: null, primary_key_position: 0 },
        { name: 'salary', data_type: 'REAL', not_null: false, default_value: null, primary_key_position: 0 },
      ],
      primary_keys: ['employee_id'],
      foreign_keys: [
        { source_column: 'department_id', target_table: 'departments', target_column: 'department_id', sequence: 0 },
      ],
      row_count: 500,
    },
    {
      name: 'departments',
      columns: [
        { name: 'department_id', data_type: 'INTEGER', not_null: true, default_value: null, primary_key_position: 1 },
        { name: 'department_name', data_type: 'TEXT', not_null: true, default_value: null, primary_key_position: 0 },
      ],
      primary_keys: ['department_id'],
      foreign_keys: [],
      row_count: 15,
    },
  ],
  total_rows: 9295,
}

export const statusPayload: SystemStatus = {
  backend: { state: 'ready', detail: 'api online' },
  database: { state: 'ready', tables: 7, rows: 9295 },
  ollama: { state: 'ready', host: 'http://localhost:11434', model: 'qwen2.5-coder:1.5b', model_loaded: true, models: [] },
  model: { state: 'ready', name: 'qwen2.5-coder:1.5b', loaded: true },
  whisper: { state: 'ready', model: 'small', backend: 'faster-whisper' },
  chroma: { state: 'ready', index_dir: 'evaluation/index/l9', built: true },
  schema: { state: 'ready' },
}

export function sampleResultResult(overrides?: Partial<PipelineResult>): PipelineResult {
  return {
    question_id: null,
    category: 'aggregate',
    reference_sql: null,
    audio: null,
    asr: null,
    normalization: {
      original_text: 'How many employees are there?',
      normalized_text: 'How many employees are there?',
      token_decisions: [
        { original: 'employees', replacement: 'employees', confidence: 1, applied: false, strategy: 'none', reason: 'exact_match', scores: {}, candidate: null },
      ],
      latency_ms: 7.2,
    },
    nlp: {
      intent: {
        primary_intent: 'AGGREGATE',
        join_required: false,
        aggregation_required: true,
        grouping_required: false,
        ordering_required: false,
        subquery_likely: false,
        confidence: 1.0,
      },
      linked_entities: [
        { entity_type: 'table', table: 'employees', column: '', match_type: 'exact', matched_text: 'employees', confidence: 1.0 },
      ],
      phrase_matches: [
        { phrase: 'how many', entity_type: 'concept', table: '', column: '', match_type: 'concept', score: 1.0, concept: 'aggregation:COUNT' },
      ],
      reranked: true,
      relationship_decisions: [],
      filtered_items_count: 3,
      latency_ms: 20.9,
    },
    retrieval: {
      query_text: 'How many employees are there?',
      retrieved_items: [
        {
          doc_type: 'column',
          doc_id: 'column:employees.employee_id',
          table: 'employees',
          column: 'employee_id',
          fk_source_table: '',
          fk_source_column: '',
          fk_target_table: '',
          fk_target_column: '',
          text: 'COLUMN: employees.employee_id\nTABLE: employees\nTYPE: INTEGER\nPRIMARY KEY: yes',
          score: 0.4434,
          distance: 0.5566,
          source: 'retrieval',
        },
      ],
      top_k: 5,
      latency_ms: 36.9,
    },
    generation: {
      raw_response: 'SELECT count(*) FROM employees',
      generated_sql: 'SELECT count(*) FROM employees',
      prompt_length: 812,
      latency_ms: 2500.0,
    },
    validation: {
      is_valid: true,
      issues: [],
      tables_used: ['employees'],
      columns_used: [],
      joins: [],
      has_aggregation: true,
      has_group_by: false,
      latency_ms: 20.0,
    },
    execution: {
      success: true,
      rows: [{ 'count(*)': 500 }],
      columns: ['count(*)'],
      error: null,
      error_type: null,
      execution_time_ms: 2.1,
      latency_ms: 3.1,
    },
    correction: null,
    final_sql: 'SELECT count(*) FROM employees',
    final_result_rows: [{ 'count(*)': 500 }],
    final_correct: false,
    final_status: 'partial',
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1,
    },
    total_latency_ms: 2590.0,
    started_at: '2026-01-01T00:00:00.000Z',
    input: {
      mode: 'text',
      question: 'How many employees are there?',
      transcript: 'How many employees are there?',
      category: 'aggregate',
      received_at: 0,
    },
    ...overrides,
  }
}

export function correctionAttempts(): PipelineResult {
  return sampleResultResult({
    correction: {
      attempts: [
        { attempt_number: 1, sql: 'SELECT * FROM employ', execution_success: false, execution_error: 'no such table: employ', execution_error_type: 'missing_table', execution_time_ms: 1, is_correct: false },
        { attempt_number: 2, sql: 'SELECT employee_name FROM employees WHERE salary > (SELECT AVG(salary) FROM employees)', execution_success: true, execution_error: null, execution_error_type: null, execution_time_ms: 1, is_correct: true },
      ],
      total_attempts: 2,
      rescued: false,
      harmed: false,
      final_correct: false,
      latency_ms: 5000.0,
    },
    final_sql: 'SELECT employee_name FROM employees WHERE salary > (SELECT AVG(salary) FROM employees)',
    category: 'complex',
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1, correction: 5000,
    },
  })
}

export function buildTextRunEvents(result: PipelineResult, question = 'How many employees are there?'): StreamEvent[] {
  return [
    {
      event: 'pipeline_started',
      mode: 'text',
      question,
      stages: [
        { key: 'normalization', label: 'Phonetic Normalization', level: 'L6' },
        { key: 'nlp', label: 'NLP + Intent', level: 'L8.1' },
        { key: 'retrieval', label: 'Schema Retrieval', level: 'L7' },
        { key: 'generation', label: 'Qwen 2.5 SQL Generation', level: 'L3' },
        { key: 'validation', label: 'SQL Validation', level: 'L4' },
        { key: 'execution', label: 'Database Execution', level: 'L4' },
        { key: 'correction', label: 'Execution-Guided Correction', level: 'L8' },
      ],
    },
    { event: 'stage_completed', stage: 'normalization', latency_ms: 7.2 },
    { event: 'stage_completed', stage: 'nlp', latency_ms: 20.9 },
    { event: 'stage_completed', stage: 'retrieval', latency_ms: 36.9 },
    { event: 'stage_completed', stage: 'generation', latency_ms: 2500 },
    { event: 'stage_completed', stage: 'validation', latency_ms: 20.0 },
    { event: 'stage_completed', stage: 'execution', latency_ms: 3.1 },
    { event: 'pipeline_completed', result },
  ]
}

export function topRecordResult(): PipelineResult {
  return sampleResultResult({
    category: 'non-aggregation',
    nlp: {
      intent: {
        primary_intent: 'SELECT',
        join_required: false,
        aggregation_required: false,
        grouping_required: false,
        ordering_required: true,
        subquery_likely: false,
        confidence: 1.0,
      },
      linked_entities: [
        { entity_type: 'table', table: 'employees', column: '', match_type: 'exact', matched_text: 'employee', confidence: 1.0 },
        { entity_type: 'column', table: 'employees', column: 'salary', match_type: 'exact', matched_text: 'salary', confidence: 1.0 },
      ],
      phrase_matches: [],
      reranked: true,
      relationship_decisions: [],
      filtered_items_count: 2,
      latency_ms: 20.9,
    },
    generation: {
      raw_response: 'SELECT employee_name, salary FROM employees ORDER BY salary DESC LIMIT 1',
      generated_sql: 'SELECT employee_name, salary FROM employees ORDER BY salary DESC LIMIT 1',
      prompt_length: 812,
      latency_ms: 2500.0,
    },
    execution: {
      success: true,
      rows: [{ employee_name: 'Mary Wright', salary: 142500 }],
      columns: ['employee_name', 'salary'],
      error: null,
      error_type: null,
      execution_time_ms: 2.1,
      latency_ms: 3.1,
    },
    final_sql: 'SELECT employee_name, salary FROM employees ORDER BY salary DESC LIMIT 1',
    final_result_rows: [{ employee_name: 'Mary Wright', salary: 142500 }],
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1,
    },
  })
}

export function topRecordSingleColumnResult(): PipelineResult {
  return sampleResultResult({
    category: 'non-aggregation',
    nlp: {
      intent: {
        primary_intent: 'SELECT',
        join_required: false,
        aggregation_required: false,
        grouping_required: false,
        ordering_required: true,
        subquery_likely: false,
        confidence: 1.0,
      },
      linked_entities: [
        { entity_type: 'table', table: 'employees', column: '', match_type: 'exact', matched_text: 'employee', confidence: 1.0 },
        { entity_type: 'column', table: 'employees', column: 'salary', match_type: 'exact', matched_text: 'salary', confidence: 1.0 },
      ],
      phrase_matches: [],
      reranked: true,
      relationship_decisions: [],
      filtered_items_count: 2,
      latency_ms: 20.9,
    },
    generation: {
      raw_response: 'SELECT employee_name FROM employees ORDER BY salary DESC LIMIT 1',
      generated_sql: 'SELECT employee_name FROM employees ORDER BY salary DESC LIMIT 1',
      prompt_length: 812,
      latency_ms: 2500.0,
    },
    execution: {
      success: true,
      rows: [{ employee_name: 'Mary Wright' }],
      columns: ['employee_name'],
      error: null,
      error_type: null,
      execution_time_ms: 2.1,
      latency_ms: 3.1,
    },
    final_sql: 'SELECT employee_name FROM employees ORDER BY salary DESC LIMIT 1',
    final_result_rows: [{ employee_name: 'Mary Wright' }],
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1,
    },
  })
}

export function averageSalaryResult(): PipelineResult {
  return sampleResultResult({
    category: 'aggregate',
    nlp: {
      intent: {
        primary_intent: 'AGGREGATE',
        join_required: false,
        aggregation_required: true,
        grouping_required: false,
        ordering_required: false,
        subquery_likely: false,
        confidence: 1.0,
      },
      linked_entities: [
        { entity_type: 'table', table: 'employees', column: '', match_type: 'exact', matched_text: 'salary', confidence: 1.0 },
      ],
      phrase_matches: [],
      reranked: true,
      relationship_decisions: [],
      filtered_items_count: 1,
      latency_ms: 20.9,
    },
    generation: {
      raw_response: 'SELECT AVG(salary) FROM employees',
      generated_sql: 'SELECT AVG(salary) FROM employees',
      prompt_length: 812,
      latency_ms: 2500.0,
    },
    execution: {
      success: true,
      rows: [{ 'AVG(salary)': 68420 }],
      columns: ['AVG(salary)'],
      error: null,
      error_type: null,
      execution_time_ms: 2.1,
      latency_ms: 3.1,
    },
    final_sql: 'SELECT AVG(salary) FROM employees',
    final_result_rows: [{ 'AVG(salary)': 68420 }],
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1,
    },
  })
}

export function listEmployeesResult(): PipelineResult {
  return sampleResultResult({
    category: 'non-aggregation',
    nlp: {
      intent: {
        primary_intent: 'SELECT',
        join_required: false,
        aggregation_required: false,
        grouping_required: false,
        ordering_required: false,
        subquery_likely: false,
        confidence: 1.0,
      },
      linked_entities: [
        { entity_type: 'table', table: 'employees', column: '', match_type: 'exact', matched_text: 'employees', confidence: 1.0 },
      ],
      phrase_matches: [],
      reranked: true,
      relationship_decisions: [],
      filtered_items_count: 1,
      latency_ms: 20.9,
    },
    generation: {
      raw_response: 'SELECT employee_name FROM employees',
      generated_sql: 'SELECT employee_name FROM employees',
      prompt_length: 812,
      latency_ms: 2500.0,
    },
    execution: {
      success: true,
      rows: [
        { employee_name: 'Mary Wright' },
        { employee_name: 'John Smith' },
        { employee_name: 'Alice Johnson' },
      ],
      columns: ['employee_name'],
      error: null,
      error_type: null,
      execution_time_ms: 2.1,
      latency_ms: 3.1,
    },
    final_sql: 'SELECT employee_name FROM employees',
    final_result_rows: [{ employee_name: 'Mary Wright' }],
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1,
    },
  })
}

export function doubleCountColumnsResult(): PipelineResult {
  return sampleResultResult({
    category: 'aggregate',
    nlp: {
      intent: {
        primary_intent: 'AGGREGATE',
        join_required: false,
        aggregation_required: true,
        grouping_required: false,
        ordering_required: false,
        subquery_likely: false,
        confidence: 1.0,
      },
      linked_entities: [],
      phrase_matches: [],
      reranked: true,
      relationship_decisions: [],
      filtered_items_count: 2,
      latency_ms: 20.9,
    },
    generation: {
      raw_response: 'SELECT COUNT(Nurse.Name) AS Total_Nurses, COUNT(Patient.Name) AS Total_Patients FROM Nurse JOIN Patient ON Nurse.SSN = Patient.SSN;',
      generated_sql: 'SELECT COUNT(Nurse.Name) AS Total_Nurses, COUNT(Patient.Name) AS Total_Patients FROM Nurse JOIN Patient ON Nurse.SSN = Patient.SSN;',
      prompt_length: 900,
      latency_ms: 2500.0,
    },
    execution: {
      success: true,
      rows: [{ Total_Nurses: 3, Total_Patients: 4 }],
      columns: ['Total_Nurses', 'Total_Patients'],
      error: null,
      error_type: null,
      execution_time_ms: 2.1,
      latency_ms: 3.1,
    },
    final_sql: 'SELECT COUNT(Nurse.Name) AS Total_Nurses, COUNT(Patient.Name) AS Total_Patients FROM Nurse JOIN Patient ON Nurse.SSN = Patient.SSN;',
    final_result_rows: [{ Total_Nurses: 3, Total_Patients: 4 }],
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1,
    },
  })
}

export function doubleCountRowsResult(): PipelineResult {
  return sampleResultResult({
    category: 'aggregate',
    nlp: {
      intent: {
        primary_intent: 'AGGREGATE',
        join_required: false,
        aggregation_required: true,
        grouping_required: false,
        ordering_required: false,
        subquery_likely: false,
        confidence: 1.0,
      },
      linked_entities: [],
      phrase_matches: [],
      reranked: true,
      relationship_decisions: [],
      filtered_items_count: 2,
      latency_ms: 20.9,
    },
    generation: {
      raw_response: 'SELECT COUNT(*) FROM Nurse UNION SELECT COUNT(*) FROM Patient;',
      generated_sql: 'SELECT COUNT(*) FROM Nurse UNION SELECT COUNT(*) FROM Patient;',
      prompt_length: 900,
      latency_ms: 2500.0,
    },
    execution: {
      success: true,
      rows: [{ 'COUNT(*)': 3 }, { 'COUNT(*)': 4 }],
      columns: ['COUNT(*)'],
      error: null,
      error_type: null,
      execution_time_ms: 2.1,
      latency_ms: 3.1,
    },
    final_sql: 'SELECT COUNT(*) FROM Nurse UNION SELECT COUNT(*) FROM Patient;',
    final_result_rows: [{ 'COUNT(*)': 3 }, { 'COUNT(*)': 4 }],
    stage_latencies: {
      normalization: 7.2, nlp: 20.9, retrieval: 36.9, generation: 2500, validation: 20.0, execution: 3.1,
    },
  })
}