export interface DecisionTableNode {
    default_next_node: string | null;
    next_error_node: string | null;
    condition_groups: ConditionGroup[];
}

export interface ConditionGroup {
    group_name: string;
    group_type: 'simple' | 'complex';
    prompt_id?: string | null;
    expression: string | null;
    conditions: Condition[];
    manipulation: string | null;
    next_node: string | null;
    valid?: boolean;
    order?: number;
    continue?: boolean;
    continue_flag?: boolean;
    route_code?: string;
    dock_visible?: boolean;
    field_expressions?: Record<string, string>;
    field_manipulations?: Record<string, string>;
}

export interface Condition {
    condition_name: string;
    condition: string;
}
