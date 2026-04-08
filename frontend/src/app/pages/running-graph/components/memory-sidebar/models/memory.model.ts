// Core memory interface matching the API response structure
export interface MemoryResponse {
    count: number;
    next: string | null;
    previous: string | null;
    results: Memory[];
}

// Base memory interface
export interface Memory {
    id: string;
    payload: MemoryPayload;
}

// Base memory payload interface
export interface MemoryPayload {
    data: string;
    hash: string;
    type: MemoryType;
    run_id: number;
    user_id: string;
    agent_id?: string; // Make agent_id optional to accommodate user memories
    created_at: string;
    updated_at?: string;
}

// Memory types from the API
export type MemoryType = 'entity' | 'short_term' | 'long_term' | 'user';

// Entity memory payload
export interface EntityMemoryPayload extends MemoryPayload {
    type: 'entity';
    relationships?: string;
}

// Short-term memory payload
export interface ShortTermMemoryPayload extends MemoryPayload {
    type: 'short_term';
    agent: string;
    observation: string;
}

// Long-term memory payload
export interface LongTermMemoryPayload extends MemoryPayload {
    type: 'long_term';
    agent: string;
    quality: number;
    suggestions?: string[];
    expected_output: string;
}

// User memory payload
export interface UserMemoryPayload extends MemoryPayload {
    type: 'user';
    // User memories don't have agent_id (it's undefined)
}

// Type guard functions to help with type narrowing
export function isEntityMemory(memory: Memory): memory is Memory & { payload: EntityMemoryPayload } {
    return memory.payload.type === 'entity';
}

export function isShortTermMemory(memory: Memory): memory is Memory & { payload: ShortTermMemoryPayload } {
    return memory.payload.type === 'short_term';
}

export function isLongTermMemory(memory: Memory): memory is Memory & { payload: LongTermMemoryPayload } {
    return memory.payload.type === 'long_term';
}

export function isUserMemory(memory: Memory): memory is Memory & { payload: UserMemoryPayload } {
    return memory.payload.type === 'user';
}
