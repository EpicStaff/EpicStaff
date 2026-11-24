import { SelectItem } from '@shared/components';
import { SidebarWidthOptions } from '@shared/services';

import { RagName, RagTypeLevel } from '../enums/rag';
import { Rag, RagStatus, RagType } from '../models/base-rag.model';

export const FILE_TYPES = ['pdf', 'csv', 'md', 'docx', 'txt', 'json', 'html'];

export const CHUNK_STRATEGIES = ['character', 'csv', 'markdown', 'HTML', 'token', 'JSON'];
export const CHUNK_STRATEGIES_SELECT_ITEMS: SelectItem[] = CHUNK_STRATEGIES.map((t) => ({
    name: t,
    value: t.toLowerCase(),
}));

export const MAX_DOCUMENT_SIZE = 20 * 1024 * 1024; // 20 MB

/** Longest "Guidance for Agents" (collection description) the backend accepts — keep in sync with
 * COLLECTION_DESCRIPTION_MAX_LENGTH in src/django_app/tables/serializers/knowledge_serializers.py. */
export const COLLECTION_DESCRIPTION_MAX_LENGTH = 2000;

/** Longest search term the graph visualization and data-table endpoints accept; longer terms are rejected with 400. */
export const GRAPH_SEARCH_MAX_LENGTH = 200;

/** Pause after the last keystroke before a graph search (visualization or data table) hits the backend. */
export const GRAPH_SEARCH_DEBOUNCE_MS = 300;

/** Error code the backend sends with a 409 for a graph that has never been indexed. */
export const GRAPH_NOT_INDEXED_ERROR_CODE = 'graph_not_indexed';

/** Shown in place of graph data while the graph exists but has never been indexed. */
export const GRAPH_NOT_INDEXED_MESSAGE = 'No index data — run indexing first';

/** Entities the visualization requests before the user touches the slider; matches the backend default (no upper cap). */
export const GRAPH_VISUALIZATION_DEFAULT_MAX_ENTITIES = 200;

/** Fewest entities the visualization endpoint accepts; lower values are rejected with 400. */
export const GRAPH_VISUALIZATION_MIN_ENTITIES = 1;

/** Most entities a single visualization request may return; higher totals are split across parallel requests. */
export const GRAPH_VISUALIZATION_MAX_ENTITIES_PER_REQUEST = 1000;

/** Most parallel pages a single visualization fetch may split into — matches the backend's page_count cap. */
export const GRAPH_VISUALIZATION_MAX_PARALLEL_PAGES = 5;

/** Most entities the visualization can show in total across all parallel requests. */
export const GRAPH_VISUALIZATION_MAX_TOTAL_ENTITIES =
    GRAPH_VISUALIZATION_MAX_ENTITIES_PER_REQUEST * GRAPH_VISUALIZATION_MAX_PARALLEL_PAGES;

/** Kept as 'graph-viz-sidebar' so widths users already saved still apply. */
export const GRAPH_VISUALIZATION_SIDEBAR_WIDTH_KEY = 'graph-viz-sidebar';
export const GRAPH_VISUALIZATION_SIDEBAR_WIDTH_OPTIONS = {
    defaultWidth: 220,
    minWidth: 160,
    maxWidth: 400,
} as const satisfies SidebarWidthOptions;

/** Kept as 'graph-viz-detail' so widths users already saved still apply. */
export const GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_KEY = 'graph-viz-detail';
export const GRAPH_VISUALIZATION_DETAIL_PANEL_WIDTH_OPTIONS = {
    defaultWidth: 320,
    minWidth: 240,
    maxWidth: 600,
} as const satisfies SidebarWidthOptions;

/** localStorage key for the "Show labels" toggle in the graph visualization toolbar. */
export const GRAPH_VISUALIZATION_LABELS_VISIBLE_KEY = 'graph-viz-labels-visible';

/** localStorage key for the "Group by community" toggle in the graph visualization toolbar. */
export const GRAPH_VISUALIZATION_GROUP_BY_COMMUNITY_KEY = 'graph-viz-group-by-community';

/** Rows per data-table page before the user picks another size; matches the backend default. */
export const GRAPH_TABLE_DEFAULT_PAGE_SIZE = 10;

/** Sidebar icon per graph data table, keyed by the table name the backend returns. */
export const GRAPH_TABLE_ICONS: Record<string, string> = {
    entities: 'graph-entities',
    relationships: 'graph-relationships',
    communities: 'graph-communities',
    documents: 'graph-documents',
    text_units: 'graph-text-units',
    community_reports: 'graph-community-reports',
    covariates: 'graph-covariates',
};

/** Icon for a table the backend returns that has no entry in GRAPH_TABLE_ICONS. */
export const GRAPH_TABLE_FALLBACK_ICON = 'database';

export const RAG_TYPE_CONFIG: Record<RagType, { name: string; icon: string }> = {
    naive: { name: 'Naive RAG', icon: 'mouse' },
    graph: { name: 'Graph RAG', icon: 'web' },
    hybrid: { name: 'Hybrid RAG', icon: 'tab-group' },
};

export const RAG_STATUS_CONFIG: Record<RagStatus, { color: string; icon: string; text: string }> = {
    new: { color: 'var(--color-ks-status-blue)', icon: 'processing', text: 'New' },
    processing: { color: 'var(--color-ks-status-processing)', icon: 'processing', text: 'Processing' },
    completed: { color: 'var(--color-ks-status-completed)', icon: 'check', text: 'Completed' },
    outdated: { color: 'var(--color-ks-status-warning)', icon: 'clock', text: 'Outdated' },
    cancelled: { color: 'var(--color-ks-status-warning)', icon: 'x', text: 'Cancelled' },
    partial: { color: 'var(--color-ks-status-warning)', icon: 'check', text: 'Partial' },
    failed: { color: 'var(--color-ks-status-failed)', icon: 'x', text: 'Failed' },
};

export const RAG_TYPES: Rag[] = [
    {
        name: RagName.NAIVE_RAG,
        value: 'naive',
        description:
            "The document is broken down into chunks, indexed, and the most relevant content for the user's query is searched for.",
        tip: 'Recommended for small collections. Minimal settings.',
        icon: 'mouse',
        level: RagTypeLevel.BASIC,
        stars: 1,
    },
    {
        name: RagName.GRAPH_RAG,
        value: 'graph',
        description:
            'A graph of entities and their relationships is created, which allows for a better understanding of the context and connections.',
        tip: 'For more complex queries and a broader context.',
        icon: 'web',
        level: RagTypeLevel.ADVANCED,
        stars: 2,
    },
    {
        name: RagName.HYBRID_RAG,
        value: 'hybrid',
        description:
            'Combines multiple data sources with different search strategies. Allows you to configure different approaches for different types of documents.',
        tip: 'Recommended for multi-source projects.',
        icon: 'tab-group',
        level: RagTypeLevel.EXPERT,
        stars: 3,
        disabled: true,
    },
];
