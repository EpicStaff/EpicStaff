export interface DeleteTarget {
    type: string;
    id: number;
    name: string;
}

export interface DeleteByModelCount {
    model: string;
    count: number;
}

export interface DeleteExternalItem {
    kind: string;
    prefix?: string;
    path?: string;
    objects?: number | null;
    bytes?: number | null;
}

export interface DeleteReport {
    dry_run: boolean;
    target: DeleteTarget;
    database: {
        total: number;
        by_model: DeleteByModelCount[];
    };
    field_updates: unknown[];
    external: DeleteExternalItem[];
}
