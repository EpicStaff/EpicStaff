export interface ExcludedExportEntity {
    type: string;
    count: number;
    names: string[];
}

/** One dependency an export job left out, as the job's result lists it. */
export interface ExcludedExportItem {
    entity_type: string;
    entity_id: number;
    /** Null when the user may not see the name. */
    name: string | null;
}
