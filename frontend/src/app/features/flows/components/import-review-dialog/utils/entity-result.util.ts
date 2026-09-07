import { EntityTypeResult, ImportResult } from '../../../../../core/models/import-result.model';
import { ENTITY_TYPE_ORDER, HIDDEN_ENTITY_TYPES } from '../constants/import-review.constants';

export function getEntityTypeResult(importResult: ImportResult, entityType: string): EntityTypeResult | undefined {
    return importResult[entityType];
}

export function getEntityTypeCount(importResult: ImportResult, entityType: string): number {
    return getEntityTypeResult(importResult, entityType)?.total || 0;
}

export function getEntityTypes(importResult: ImportResult): string[] {
    const keys = new Set(Object.keys(importResult).filter((k) => !HIDDEN_ENTITY_TYPES.has(k)));
    return Array.from(keys).sort((a, b) => {
        const ai = ENTITY_TYPE_ORDER.indexOf(a);
        const bi = ENTITY_TYPE_ORDER.indexOf(b);
        if (ai === -1 && bi === -1) return a.localeCompare(b);
        if (ai === -1) return 1;
        if (bi === -1) return -1;
        return ai - bi;
    });
}

export function getVisibleEntityTypes(importResult: ImportResult): string[] {
    return getEntityTypes(importResult).filter((et) => getEntityTypeCount(importResult, et) > 0);
}

export function getTotalItemsCount(importResult: ImportResult): number {
    let total = 0;
    Object.entries(importResult).forEach(([key, result]) => {
        if (result && !HIDDEN_ENTITY_TYPES.has(key)) total += result.total;
    });
    return total;
}
