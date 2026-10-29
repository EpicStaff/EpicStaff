import { BulkDeleteGroup, BulkDeleteItem, BulkDeleteLabel, BulkDeleteTarget } from '@shared/models';

/** `llm` / `embedding` plus one entry per voice provider — matches the LLM Library tab's sections. */
export type LlmLibrarySelectionKind = 'llm' | 'embedding' | 'openai' | 'elevenlabs' | 'gemini';

/** A selected card's key, built as `` `${kind}:${id}` `` since ids overlap across the underlying tables. */
export function llmLibrarySelectionKey(kind: LlmLibrarySelectionKind, id: number): string {
    return `${kind}:${id}`;
}

/** What a kind needs in order to turn its selected ids into a `BulkDeleteGroup`. */
export interface LlmLibraryBulkDeleteSource {
    label: BulkDeleteLabel;
    target: BulkDeleteTarget;
    /** That kind's current storage contents, used to resolve a selected id to its display name. */
    configs: readonly { id: number; custom_name: string }[];
}

/**
 * Turns the selected `kind:id` keys into one `BulkDeleteGroup` per kind that has a selection.
 * Ids no longer present in their kind's storage are dropped; a kind left with no items is omitted entirely.
 */
export function llmLibraryBulkDeleteGroups(
    selectedKeys: ReadonlySet<string>,
    sources: Record<LlmLibrarySelectionKind, LlmLibraryBulkDeleteSource>
): BulkDeleteGroup[] {
    const idsByKind = new Map<LlmLibrarySelectionKind, number[]>();

    for (const key of selectedKeys) {
        const [kind, idPart] = key.split(':') as [string, string | undefined];
        const id = Number(idPart);
        if (!isSelectionKind(kind, sources) || idPart === undefined || Number.isNaN(id)) continue;

        const ids = idsByKind.get(kind);
        if (ids) {
            ids.push(id);
        } else {
            idsByKind.set(kind, [id]);
        }
    }

    const groups: BulkDeleteGroup[] = [];
    for (const [kind, ids] of idsByKind) {
        const source = sources[kind];
        const items = resolveItems(ids, source.configs);
        if (items.length === 0) continue;

        groups.push({ target: source.target, label: source.label, items });
    }

    return groups;
}

function resolveItems(
    ids: readonly number[],
    configs: readonly { id: number; custom_name: string }[]
): BulkDeleteItem[] {
    const items: BulkDeleteItem[] = [];
    for (const id of ids) {
        const config = configs.find((candidate) => candidate.id === id);
        if (!config) continue;
        items.push({ id, name: config.custom_name });
    }
    return items;
}

function isSelectionKind(
    kind: string,
    sources: Record<LlmLibrarySelectionKind, LlmLibraryBulkDeleteSource>
): kind is LlmLibrarySelectionKind {
    return kind in sources;
}
