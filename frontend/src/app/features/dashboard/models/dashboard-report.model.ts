import { GraphSessionStatus } from '@shared/models';

export enum DashboardTriggerType {
    Schedule = 'schedule',
    Webhook = 'webhook',
    Telegram = 'telegram',
}

export interface DashboardTotals {
    agents: number;
    flows: number;
    roles_builtin: number;
    roles_custom: number;
    users: number;
    knowledge_total: number;
    knowledge_naive: number;
    knowledge_graph: number;
    knowledge_not_indexed: number;
    files: number;
    files_bytes: number;
    llm_configs: number;
    embedding_configs: number;
    realtime_configs: number;
    tools_python: number;
    tools_mcp: number;
    plugins: number;
}

export interface DashboardActiveTrigger {
    trigger_type: DashboardTriggerType;
    node_id: number;
    node_name: string;
    graph_id: number;
    graph_name: string;
    next_run_at: string | null;
}

export interface DashboardLiveSession {
    session_id: number;
    graph_id: number;
    graph_name: string;
    status: GraphSessionStatus;
    created_at: string;
}

export interface DashboardKnowledgeUsage {
    rag_type: 'naive' | 'graph';
    collections: number;
    embedding_tokens: number;
    llm_input_tokens: number;
    llm_output_tokens: number;
    cost_usd: string;
    unknown_cost_count: number;
}

export interface DashboardReport {
    built_at: string;
    next_build_at: string | null;
    totals: DashboardTotals;
    active_triggers: DashboardActiveTrigger[];
    live_sessions: DashboardLiveSession[];
    knowledge_usage: DashboardKnowledgeUsage[];
}
