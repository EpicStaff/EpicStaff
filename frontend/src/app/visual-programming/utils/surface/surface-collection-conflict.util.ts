export interface HasKnowledgeCollections {
    knowledge: { collection: number }[];
}

export interface SurfaceLike extends HasKnowledgeCollections {
    name?: string;
}

export function collectionIdsOf(surface: HasKnowledgeCollections | null | undefined): number[] {
    return surface?.knowledge.map((k) => k.collection) ?? [];
}

export function truncateName(name: string, maxLength = 24): string {
    return name.length > maxLength ? `${name.slice(0, maxLength - 1)}…` : name;
}

export function findConflictingCollectionOwner(
    candidateCollectionIds: readonly number[],
    usedCollectionOwners: ReadonlyMap<number, string>
): string | null {
    for (const id of candidateCollectionIds) {
        const owner = usedCollectionOwners.get(id);
        if (owner !== undefined) return owner;
    }
    return null;
}

export function surfaceCollectionConflictMessage(ownerName: string): string {
    return `The same collection is used by "${ownerName}" — a collection may appear in only one surface per node.`;
}

export function surfaceReplacedMessage(removedNames: readonly string[]): string {
    const list = removedNames.map((name) => `"${name}"`).join(', ');
    return `Removed ${list} — a collection may appear in only one surface per node.`;
}

export interface SurfacesChangeResult {
    selectedSurfaceIds: number[];
    clearInline: boolean;
    conflictMessages: string[];
}

export function computeSurfacesChangeResult(
    values: readonly unknown[],
    localSurfaceValue: unknown,
    previousIds: readonly number[],
    surfacesById: ReadonlyMap<number, SurfaceLike>,
    inlineSurface: HasKnowledgeCollections | null,
    hasLocalSurface: boolean
): SurfacesChangeResult {
    const realIds = values.filter((v): v is number => v !== localSurfaceValue) as number[];
    const keepsInline = hasLocalSurface && values.includes(localSurfaceValue);

    const usedCollectionOwners = new Map<number, string>();
    if (keepsInline) {
        collectionIdsOf(inlineSurface).forEach((c) => usedCollectionOwners.set(c, 'Local surface'));
    }

    const accepted: number[] = [];
    const conflictMessages: string[] = [];
    const stillSelected = realIds.filter((id) => previousIds.includes(id));
    const newlyAdded = realIds.filter((id) => !previousIds.includes(id));

    for (const id of stillSelected) {
        const surface = surfacesById.get(id);
        accepted.push(id);
        collectionIdsOf(surface).forEach((c) =>
            usedCollectionOwners.set(c, truncateName(surface?.name ?? 'this node'))
        );
    }
    for (const id of newlyAdded) {
        const surface = surfacesById.get(id);
        const collections = collectionIdsOf(surface);
        const conflictOwner = findConflictingCollectionOwner(collections, usedCollectionOwners);
        if (conflictOwner !== null) {
            conflictMessages.push(surfaceCollectionConflictMessage(conflictOwner));
            continue;
        }
        accepted.push(id);
        collections.forEach((c) => usedCollectionOwners.set(c, truncateName(surface?.name ?? 'this node')));
    }

    return {
        selectedSurfaceIds: accepted,
        clearInline: hasLocalSurface && !values.includes(localSurfaceValue),
        conflictMessages,
    };
}

export interface LocalSurfaceApplyResult {
    selectedSurfaceIds: number[];
    removedNames: string[];
}

export function computeApplyLocalSurfaceResult(
    inline: HasKnowledgeCollections,
    selectedSurfaceIds: readonly number[],
    surfacesById: ReadonlyMap<number, SurfaceLike>
): LocalSurfaceApplyResult {
    const inlineCollections = new Set(collectionIdsOf(inline));
    const removedNames: string[] = [];
    const kept = selectedSurfaceIds.filter((id) => {
        const surface = surfacesById.get(id);
        const conflicts = collectionIdsOf(surface).some((c) => inlineCollections.has(c));
        if (conflicts) removedNames.push(truncateName(surface?.name ?? `Surface #${id}`));
        return !conflicts;
    });
    return { selectedSurfaceIds: kept, removedNames };
}

export interface AutoSelectResult {
    accepted: number[];
    conflictMessages: string[];
}

export function computeAutoSelectResult(
    candidateIds: readonly number[],
    currentSelectedIds: readonly number[],
    surfacesById: ReadonlyMap<number, SurfaceLike>,
    inlineSurface: HasKnowledgeCollections | null
): AutoSelectResult {
    const usedCollectionOwners = new Map<number, string>();
    collectionIdsOf(inlineSurface).forEach((c) => usedCollectionOwners.set(c, 'Local surface'));
    for (const id of currentSelectedIds) {
        const surface = surfacesById.get(id);
        collectionIdsOf(surface).forEach((c) =>
            usedCollectionOwners.set(c, truncateName(surface?.name ?? 'this node'))
        );
    }

    const accepted: number[] = [];
    const conflictMessages: string[] = [];
    for (const id of candidateIds) {
        if (currentSelectedIds.includes(id)) continue;
        const surface = surfacesById.get(id);
        const collections = collectionIdsOf(surface);
        const conflictOwner = findConflictingCollectionOwner(collections, usedCollectionOwners);
        if (conflictOwner !== null) {
            conflictMessages.push(surfaceCollectionConflictMessage(conflictOwner));
            continue;
        }
        accepted.push(id);
        collections.forEach((c) => usedCollectionOwners.set(c, truncateName(surface?.name ?? 'this node')));
    }

    return { accepted, conflictMessages };
}
