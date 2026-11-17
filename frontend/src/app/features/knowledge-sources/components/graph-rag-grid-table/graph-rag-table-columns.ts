import { GraphGridColumnDef } from './graph-rag-grid-table.model';

/** Action names emitted by the grid's `actionClick`; the data-tables container routes each one. */
export const GRAPH_ACTION_VIEW_COMMUNITY_REPORT = 'view-community-report';
export const GRAPH_ACTION_VIEW_COMMUNITY = 'view-community';
export const GRAPH_ACTION_VIEW_DOCUMENT = 'view-document';

const ACTION_COLUMN_WIDTH = '50px';

const viewActionColumn = (actionName: string, tooltip: string): GraphGridColumnDef => ({
    key: 'actions',
    width: ACTION_COLUMN_WIDTH,
    pinned: 'end',
    action: { name: actionName, icon: 'eye', tooltip },
});

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
        viewActionColumn(GRAPH_ACTION_VIEW_COMMUNITY_REPORT, 'Open community report'),
    ],
    documents: [
        { key: 'id', width: '100px' },
        { key: 'human_readable_id', label: 'Human Readable Id', width: '180px' },
        { key: 'title' },
        viewActionColumn(GRAPH_ACTION_VIEW_DOCUMENT, 'Preview document'),
    ],
    text_units: [{ key: 'id', width: '280px' }, { key: 'text' }, { key: 'n_tokens', label: 'Tokens', width: '100px' }],
    community_reports: [
        { key: 'id', width: '150px' },
        { key: 'community', label: 'Community', width: '120px' },
        { key: 'title', width: '300px' },
        { key: 'summary' },
        viewActionColumn(GRAPH_ACTION_VIEW_COMMUNITY, 'Open community'),
    ],
    covariates: [
        { key: 'id', width: '280px' },
        { key: 'subject_id', width: '200px' },
        { key: 'subject_type', width: '150px' },
        { key: 'covariate_type', width: '150px' },
        { key: 'description' },
    ],
};
