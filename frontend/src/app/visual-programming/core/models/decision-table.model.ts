export interface DecisionTableNode {
    default_next_node: string | null;
    next_error_node: string | null;
    condition_groups: ConditionGroup[];
}

export interface ConditionGroup {
    group_name: string;
    group_type: 'simple' | 'complex';
    expression: string | null;
    conditions: Condition[];
    manipulation: string | null;
    next_node: string | null;
    valid?: boolean;
    order?: number;
}

export interface Condition {
    condition_name: string;
    condition: string;
}
