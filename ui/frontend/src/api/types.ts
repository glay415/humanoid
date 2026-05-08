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

export type LowLevelEvent = {
  state: InternalState;
  raw_core_affect: CoreAffect;
  mood: CoreAffect;
  drives: Drives;
  fast_path_triggered: boolean;
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

// Discriminated union for the SSE stream.
export type TurnEvent =
  | { type: 'low_level'; data: LowLevelEvent }
  | { type: 'emotion'; data: EmotionEvent }
  | { type: 'memory'; data: MemoryEvent }
  | { type: 'candidates'; data: CandidatesEvent }
  | { type: 'final'; data: FinalEvent }
  | { type: 'tone'; data: ToneEvent }
  | { type: 'done'; data: DoneEvent }
  | { type: 'error'; data: ErrorEvent };

export type TurnEventName = TurnEvent['type'];
