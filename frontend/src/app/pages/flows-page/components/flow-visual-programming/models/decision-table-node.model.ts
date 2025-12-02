export interface ConditionGroupBackend {
    id: number;
    decision_table_node: number;
    group_name: string;
    group_type: string;
    expression: string | null;
    conditions: ConditionBackend[];
    manipulation: string | null;
    next_node: string | null;
    order: number;
}

export interface CreateConditionGroupRequest {
    group_name: string;
    group_type: string;
    expression: string | null;
    conditions: CreateConditionRequest[];
    manipulation: string | null;
    next_node: string | null;
    order: number;
}

export interface ConditionBackend {
    id: number;
    condition_group: number;
    condition_name: string;
    condition: string;
}

export interface CreateConditionRequest {
    condition_name: string;
    condition: string;
}

export interface GetDecisionTableNodeRequest {
    id: number;
    graph: number;
    node_name: string;
    condition_groups: ConditionGroupBackend[];
    default_next_node: string | null;
    next_error_node: string | null;
}

export interface CreateDecisionTableNodeRequest {
    graph: number;
    node_name: string;
    condition_groups: CreateConditionGroupRequest[];
    default_next_node: string | null;
    next_error_node: string | null;
}

