import { generateUuid } from '@shared/utils';

/** Per-section metadata persisted alongside the section record. */
export interface CdtSectionMetadata {
    color?: string;
}

/** A named, coloured group of CDT condition rows. `id` is what `ConditionGroup.section` points at. */
export interface CdtSection {
    id: string;
    name: string;
    metadata: CdtSectionMetadata;
}

export interface CdtSectionColorOption {
    /** Stable palette key. */
    id: 'default' | 'purple' | 'blue' | 'green' | 'orange' | 'red';
    /** The value persisted in `metadata.color`. */
    hex: string;
}

/**
 * Palette hexes mirror `features/flows/models/label.model.ts` `LABEL_COLOR_OPTIONS.circleBg`
 * 1:1 (same colours, same order). These are persisted data (the value travels to the backend
 * in `metadata.color`), not styling tokens, so literal hex here is intentional.
 */
export const CDT_SECTION_COLOR_OPTIONS: readonly CdtSectionColorOption[] = [
    { id: 'default', hex: '#D9D9D9' },
    { id: 'purple', hex: '#685FFF' },
    { id: 'blue', hex: '#48CBFF' },
    { id: 'green', hex: '#2ABA6B' },
    { id: 'orange', hex: '#FF8F3F' },
    { id: 'red', hex: '#F54242' },
];

export const CDT_SECTION_DEFAULT_COLOR: string = CDT_SECTION_COLOR_OPTIONS[0].hex;

/** Creates a new section with a fresh id. `color` falls back to the default palette colour. */
export function createCdtSection(name: string, color?: string | null): CdtSection {
    return {
        id: generateUuid(),
        name,
        metadata: { color: normalizeCdtSectionColor(color) },
    };
}

const HEX_COLOR_PATTERN = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** Normalises a persisted colour value without discarding data */
export function normalizeCdtSectionColor(color?: string | null): string {
    if (!color) return CDT_SECTION_DEFAULT_COLOR;
    const trimmed = color.trim();
    if (!HEX_COLOR_PATTERN.test(trimmed)) return CDT_SECTION_DEFAULT_COLOR;
    const match = CDT_SECTION_COLOR_OPTIONS.find((option) => option.hex.toLowerCase() === trimmed.toLowerCase());
    return match ? match.hex : trimmed.toUpperCase();
}

/** Resolves the display colour for a section, normalised against the palette. */
export function getCdtSectionColor(section: CdtSection | null | undefined): string {
    return normalizeCdtSectionColor(section?.metadata?.color);
}

/** Looks up a section by id, returning `null` when `id` is missing or not found. */
export function findCdtSection(sections: readonly CdtSection[], id: string | null | undefined): CdtSection | null {
    if (!id) return null;
    return sections.find((section) => section.id === id) ?? null;
}

/**
 * Back-compat: synthesise entries for section ids referenced by rows but absent from `sections`.
 */
export function reconcileCdtSections(
    sections: readonly CdtSection[],
    referencedIds: readonly (string | null | undefined)[]
): CdtSection[] {
    const knownIds = new Set(sections.map((section) => section.id));
    const usedNames = new Set(sections.map((section) => section.name));
    const synthesised: CdtSection[] = [];
    const seen = new Set<string>();
    let groupNumber = 0;

    for (const id of referencedIds) {
        if (!id || knownIds.has(id) || seen.has(id)) continue;
        seen.add(id);

        let name: string;
        do {
            groupNumber += 1;
            name = `Group ${groupNumber}`;
        } while (usedNames.has(name));
        usedNames.add(name);

        synthesised.push({
            id,
            name,
            metadata: { color: CDT_SECTION_DEFAULT_COLOR },
        });
    }

    return [...sections, ...synthesised];
}

/** Drops sections no longer referenced by any row (Ungroup / delete rows / cross-group move). */
export function pruneCdtSections(
    sections: readonly CdtSection[],
    referencedIds: readonly (string | null | undefined)[]
): CdtSection[] {
    const referenced = new Set(referencedIds.filter((id): id is string => !!id));
    return sections.filter((section) => referenced.has(section.id));
}
