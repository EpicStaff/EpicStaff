import { GraphGridColumnDef } from './graph-rag-grid-table.model';

export const GRAPH_TABLE_COLUMNS: Record<string, GraphGridColumnDef[]> = {
    entities: [
        { key: 'id', width: '150px' },
        { key: 'title', width: '200px' },
        { key: 'type', width: '150px' },
        { key: 'description' },
        { key: 'degree', width: '100px' },
    ],
    relationships: [
        { key: 'id', width: '150px' },
        { key: 'source', width: '200px' },
        { key: 'target', width: '200px' },
        { key: 'description' },
        { key: 'weight', width: '100px' },
    ],
    communities: [
        { key: 'id', width: '280px' },
        { key: 'title' },
        { key: 'level', width: '100px' },
        { key: 'size', width: '100px' },
    ],
    documents: [
        { key: 'id', width: '100px' },
        { key: 'human_readable_id', label: 'Human Readable Id', width: '180px' },
        { key: 'title' },
    ],
    text_units: [{ key: 'id', width: '280px' }, { key: 'text' }, { key: 'n_tokens', label: 'Tokens', width: '100px' }],
    community_reports: [{ key: 'id', width: '150px' }, { key: 'title', width: '300px' }, { key: 'summary' }],
    covariates: [
        { key: 'id', width: '280px' },
        { key: 'subject_id', width: '200px' },
        { key: 'subject_type', width: '150px' },
        { key: 'covariate_type', width: '150px' },
        { key: 'description' },
    ],
};
