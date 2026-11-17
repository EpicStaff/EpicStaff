const STORAGE_KEY_PREFIX = 'app-table-layout';
/** Narrowest a resized column gets: still fits a short header label. */
export const MIN_COLUMN_WIDTH = 80;
/** Widest a resized column gets; gives the resize separator a real range for assistive tech. */
export const MAX_COLUMN_WIDTH = 1600;

/** `maxWidth` lowers the ceiling below MAX_COLUMN_WIDTH, e.g. to a share of the table's visible width. */
export function clampColumnWidth(width: number, maxWidth: number = MAX_COLUMN_WIDTH): number {
    return Math.round(Math.min(maxWidth, MAX_COLUMN_WIDTH, Math.max(MIN_COLUMN_WIDTH, width)));
}

/** What a user customized in a table: which columns show and how wide (px) the resized ones are. */
export interface TableLayout {
    visibility: Record<string, boolean>;
    widths: Record<string, number>;
}

export function emptyTableLayout(): TableLayout {
    return { visibility: {}, widths: {} };
}

/** Never throws: missing storage, broken JSON or entries of the wrong type fall back to the defaults. */
export function readTableLayout(layoutKey: string | null): TableLayout {
    if (!layoutKey) return emptyTableLayout();
    try {
        const raw = localStorage.getItem(`${STORAGE_KEY_PREFIX}:${layoutKey}`);
        if (!raw) return emptyTableLayout();
        const parsed: unknown = JSON.parse(raw);
        if (!isRecord(parsed)) return emptyTableLayout();
        return {
            visibility: pickEntries(parsed['visibility'], (value): value is boolean => typeof value === 'boolean'),
            widths: Object.fromEntries(
                Object.entries(
                    pickEntries(
                        parsed['widths'],
                        (value): value is number => typeof value === 'number' && Number.isFinite(value) && value > 0
                    )
                ).map(([key, width]) => [key, clampColumnWidth(width)])
            ),
        };
    } catch {
        return emptyTableLayout();
    }
}

export function writeTableLayout(layoutKey: string | null, layout: TableLayout): void {
    if (!layoutKey) return;
    try {
        localStorage.setItem(`${STORAGE_KEY_PREFIX}:${layoutKey}`, JSON.stringify(layout));
    } catch {
        // Storage unavailable (private mode, quota): the layout still applies for this session.
    }
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function pickEntries<T>(value: unknown, isValid: (entry: unknown) => entry is T): Record<string, T> {
    if (!isRecord(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, entry]) => isValid(entry))) as Record<string, T>;
}
