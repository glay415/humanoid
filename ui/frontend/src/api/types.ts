// API type definitions for the v12 cognitive architecture backend.
// Mirrors the contract documented in the wave6 task brief.

export type InternalState = {
  reward: number;
  patience: number;
  arousal: number;
  learning: number;
  excitation: number;
  inhibition: number;
  stress: number;
  bonding: number;
  comfort: number;
};

export type InternalStateKey = keyof InternalState;

export type DriveSet = {
  curiosity: number;
  bonding: number;
  preservation: number;
  safety: number;
  pleasure: number;
};

export type DriveKey = keyof DriveSet;

export type Drives = {
  fulfillment: DriveSet;
  deficits: DriveSet;
  max_deficit: number;
};

export type CoreAffect = {
  valence: number;
  arousal: number;
};

export type MoodPoint = {
  turn: number;
  valence: number;
  arousal: number;
};

export type Marker = {
  pattern_id: string;
  valence: number;
  strength: number;
  age: number;
};

export type SelfModel = {
  narrative: string;
  confidence: number;
};

export type ServerState = {
  turn_number: number;
  internal_state: InternalState;
  baselines: InternalState;
  mood_history: MoodPoint[];
  drives: Drives;
  raw_core_affect: CoreAffect;
  markers: Marker[];
  self_model: SelfModel;
  meta_resource: number;
  // Present on instance-scoped /api/instances/{id} responses; absent on the
  // legacy /api/state route.
  instance_id?: string;
  display_name?: string;
};

// Persona catalog and multi-instance spawn types (wave11).

export type PersonaSummary = {
  key_baselines: Record<string, number>;
  key_traits: string[];
};

export type PersonaInfo = {
  id: string;
  display_name: string;
  description: string;
  summary: PersonaSummary;
};

export type InstanceCard = {
  instance_id: string;
  display_name: string;
  persona_id: string;
  persona_display_name: string;
  turn_number: number;
  last_mood: CoreAffect;
  last_active: string;  // ISO 8601
  created_at: string;   // ISO 8601
};

export type SpawnRequest = {
  persona_id: string;
  display_name?: string;
  jitter?: number; // 0..1
};

// Wave 12: hard reset (per-instance) + global wipe (admin) operations.
export type WipeRequest = { confirm: string };
export type WipeResponse = { removed: number };

// Per-event payloads emitted on /api/turn.

// Wave14E: optional verbose debug payload appended to LowLevelEvent when
// the turn was requested with debug=true. Off by default.

export type ExperienceVectorDims = {
  reward: number;
  novelty: number;
  threat: number;
  social_reward: number;
  goal_progress: number;
};

export type MatrixDecomposition = {
  // Each term is a 9-param dict (InternalState shape).
  a_exp_term: InternalState;
  w_dev_term: InternalState;
  d_recovery_term: InternalState;
  delta_clamped: InternalState;
  exp_vec: ExperienceVectorDims;
};

export type EigenvalueSpectrum = {
  real_parts: number[];
  max_real: number;
};

export type MoodStepTrace = {
  before: CoreAffect;
  raw: CoreAffect;
  eta_step: CoreAffect;
  after: CoreAffect;
};

export type DriftStepTrace = {
  baseline_ema_before: InternalState;
  baseline_ema_after: InternalState;
  drift_delta_norm: number;
};

export type LowLevelDebugPayload = {
  matrix_decomp: MatrixDecomposition;
  eigenvalues: EigenvalueSpectrum;
  mood_step: MoodStepTrace;
  drift_step: DriftStepTrace;
};

export type LowLevelEvent = {
  state: InternalState;
  raw_core_affect: CoreAffect;
  mood: CoreAffect;
  drives: Drives;
  fast_path_triggered: boolean;
  debug?: LowLevelDebugPayload | null;
};

export type EmotionEvent = {
  valence: number;
  arousal: number;
  preliminary_labels: string[];
  experience_dimensions: {
    reward: number;
    threat: number;
    novelty: number;
  };
};

export type MemoryEvent = {
  memories: unknown[];
  prospective_items: unknown[];
  retrieval_context: Record<string, unknown>;
};

export type CandidateStyle = 'emotional' | 'restrained' | 'humor' | 'silence';

export type CandidatesEvent = Array<{
  style: CandidateStyle;
  text: string;
}>;

export type MarkerMatch = 'approach' | 'avoid' | 'none';

export type FinalEvent = {
  selected_index: number;
  text: string;
  rationale: string;
  marker_match: MarkerMatch;
};

export type ToneAction = 'pass' | 'tone_adjust' | 'regenerate';

export type ToneEvent = {
  action: ToneAction;
  tone_eval: {
    response_valence: number;
    response_arousal: number;
    rationale: string;
  };
  recommended_delay_ms: number;
};

export type DoneEvent = {
  response: string;
  turn_number: number;
  experience_vector: Record<string, unknown>;
};

export type ErrorEvent = {
  stage: string;
  message: string;
};

export type ResponseChunkEvent = {
  text: string;
};

// Discriminated union for the SSE stream.
export type TurnEvent =
  | { type: 'low_level'; data: LowLevelEvent }
  | { type: 'emotion'; data: EmotionEvent }
  | { type: 'memory'; data: MemoryEvent }
  | { type: 'candidates'; data: CandidatesEvent }
  | { type: 'final'; data: FinalEvent }
  | { type: 'tone'; data: ToneEvent }
  | { type: 'response_chunk'; data: ResponseChunkEvent }
  | { type: 'done'; data: DoneEvent }
  | { type: 'error'; data: ErrorEvent };

export type TurnEventName = TurnEvent['type'];

// ---------------------------------------------------------------------------
// Wave 14D — JSONL 로그 항목 (인스턴스별 turns/events/drift)
// ---------------------------------------------------------------------------

export type TurnsLogEntry = {
  ts: string;
  turn: number;
  user_input_len: number;
  response_len: number;
  state: Record<string, number>;
  raw_core_affect: { valence: number; arousal: number };
  mood: { valence: number; arousal: number };
  drives_fulfillment: Record<string, number>;
  drives_max_deficit: number;
  emotion_valence: number;
  emotion_arousal: number;
  emotion_labels: string[];
  experience_dimensions: Record<string, number>;
  experience_vector: Record<string, number>;
  action: 'pass' | 'tone_adjust' | 'regenerate';
  selected_index: number;
  marker_match: 'approach' | 'avoid' | 'none';
  recommended_delay_ms: number;
  duration_ms: number;
  llm_calls: number;
  tokens_input: number;
  tokens_output: number;
};

export type EventsLogType =
  | 'marker_formed'
  | 'marker_decayed'
  | 'trigger_fired'
  | 'reappraisal'
  | 'fast_path_match'
  | 'dmn_activity'
  | 'auto_encode'
  | 'llm_error';

export type EventsLogEntry = {
  ts: string;
  type: string;
  payload: Record<string, unknown>;
  turn: number;
};

export type DriftLogEntry = {
  ts: string;
  turn: number;
  baselines: Record<string, number>;
  baseline_ema: Record<string, number>;
  drift_delta_norm: number;
};
