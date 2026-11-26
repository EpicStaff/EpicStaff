/** The 7 target tables the backend accepts for the linked_to_type cross-table filter. */
export const LINKED_TO_TARGET_TYPES = [
    'entities',
    'relationships',
    'communities',
    'community_reports',
    'text_units',
    'documents',
    'covariates',
] as const;

export type LinkedToTargetType = (typeof LINKED_TO_TARGET_TYPES)[number];

interface LinkedToTargetTab {
    type: LinkedToTargetType;
    label: string;
}

/**
 * Labels for every target type. Keying off `Record<LinkedToTargetType, string>` turns a missing
 * entry into a compile error — `LINKED_TO_TARGET_TABS` and the backend tabs stay in sync.
 */
export const LINKED_TO_LABEL_BY_TYPE: Record<LinkedToTargetType, string> = {
    entities: 'Entities',
    relationships: 'Relationships',
    communities: 'Communities',
    community_reports: 'Community reports',
    text_units: 'Text units',
    documents: 'Documents',
    covariates: 'Covariates',
};

export const LINKED_TO_TARGET_TABS: readonly LinkedToTargetTab[] = LINKED_TO_TARGET_TYPES.map((type) => ({
    type,
    label: LINKED_TO_LABEL_BY_TYPE[type],
}));

/** Longest row text (first ~N chars) to display in the picker list for long-text rows. */
const LINKED_TO_ROW_TEXT_LIMIT = 60;

/** Rows per page fetched from the backend for each tab's list. */
export const LINKED_TO_PICKER_PAGE_SIZE = 20;

/**
 * Picks a short, readable label for one row of a target table. The id is always available as a
 * fallback; some tables have no obvious human-readable field, in which case we show the id.
 */
export function pickLinkedToRowLabel(type: LinkedToTargetType, row: Record<string, unknown>): string {
    const id = String(row['id'] ?? '');
    switch (type) {
        case 'entities':
        case 'communities':
        case 'community_reports':
        case 'documents': {
            const title = typeof row['title'] === 'string' ? row['title'].trim() : '';
            return title || id;
        }
        case 'relationships': {
            const source = typeof row['source'] === 'string' ? row['source'] : '';
            const target = typeof row['target'] === 'string' ? row['target'] : '';
            if (source && target) return `${source} → ${target}`;
            return id;
        }
        case 'text_units': {
            const text = typeof row['text'] === 'string' ? row['text'] : '';
            return truncate(text, LINKED_TO_ROW_TEXT_LIMIT) || id;
        }
        case 'covariates': {
            const description = typeof row['description'] === 'string' ? row['description'] : '';
            return truncate(description, LINKED_TO_ROW_TEXT_LIMIT) || id;
        }
    }
}

function truncate(value: string, limit: number): string {
    const trimmed = value.trim();
    if (trimmed.length <= limit) return trimmed;
    return `${trimmed.slice(0, limit).trimEnd()}…`;
}
