export interface GetCodeAgentNodeRequest {
    id: number;
    node_name: string;
    graph: number;
    llm_config: number | null;
    agent_mode: string;
    session_id: string;
    system_prompt: string;
    stream_handler_code: string;
    libraries: string[];
    polling_interval_ms: number;
    silence_indicator_s: number;
    indicator_repeat_s: number;
    chunk_timeout_s: number;
    inactivity_timeout_s: number;
    max_wait_s: number;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    stream_config?: Record<string, boolean>;
    output_schema?: Record<string, any>;
    metadata?: Record<string, any>;
}

export interface CreateCodeAgentNodeRequest {
    node_name: string;
    graph: number;
    llm_config: number | null;
    agent_mode: string;
    session_id: string;
    system_prompt: string;
    stream_handler_code: string;
    libraries: string[];
    polling_interval_ms: number;
    silence_indicator_s: number;
    indicator_repeat_s: number;
    chunk_timeout_s: number;
    inactivity_timeout_s: number;
    max_wait_s: number;
    input_map: Record<string, any>;
    output_variable_path: string | null;
    stream_config?: Record<string, boolean>;
    output_schema?: Record<string, any>;
    metadata?: Record<string, any>;
}

export interface CodeAgentNodeData {
    llm_config_id: number | null;
    agent_mode: string;
    session_id: string;
    system_prompt: string;
    stream_handler_code: string;
    libraries: string[];
    polling_interval_ms: number;
    silence_indicator_s: number;
    indicator_repeat_s: number;
    chunk_timeout_s: number;
    inactivity_timeout_s: number;
    max_wait_s: number;
    stream_config?: Record<string, boolean>;
    output_schema?: Record<string, any>;
}
