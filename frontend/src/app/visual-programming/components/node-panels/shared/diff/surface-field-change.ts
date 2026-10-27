import { InlineSurface } from '../../../../core/models/task-node.model';
import { fieldChangeFor, FieldName, showsFieldMarks, UnionNodeDiffState } from '../../../../utils/diff';
import { DiffFieldMarkChange } from '../../../diff-field-mark/diff-field-mark.component';

/** The surfaces of an Agent or Task node as the panel shows them (the version's): one field shows both. */
export interface NodeSurfaces {
    surfaceList: readonly number[];
    inlineSurface: InlineSurface | null;
}

/** Every field the surface field of the panel shows. */
const SURFACE_FIELDS: readonly FieldName[] = [
    'surface_list',
    'inline_surface',
    'inline_surface.instructions',
    'inline_surface.python_tools',
    'inline_surface.mcp_tools',
];

/** The one item for the local surface: its instructions and tools are not listed (they would clog the tooltip). */
const LOCAL_SURFACE_ITEM = 'Local surface';

/**
 * The change of the surface field of an Agent or Task panel, which shows the surfaces picked (`surface_list`) and
 * the local surface (`inline_surface`) as one value: each side as a list, so the tooltip strikes what a restore
 * removes. The list holds each surface by its name (`surfaceName`), then "Local surface" when the side has one. A
 * change inside the local surface (its instructions or tools) still marks the field, with nothing struck. `null` when
 * the node shows no field marks or none of these fields changed.
 */
export function surfaceFieldChange(
    diff: UnionNodeDiffState | null,
    version: NodeSurfaces,
    surfaceName: (id: unknown) => string
): DiffFieldMarkChange | null {
    if (diff === null || !showsFieldMarks(diff)) return null;
    if (SURFACE_FIELDS.every((field) => fieldChangeFor(diff, field) === null)) return null;

    const surfaceListChange = fieldChangeFor(diff, 'surface_list');
    const currentList = surfaceListChange ? asList(surfaceListChange.current) : version.surfaceList;
    // A restore adds or removes the local surface whole; any other change of it keeps it on both sides.
    const localSurfaceChange = fieldChangeFor(diff, 'inline_surface');
    const currentHasLocal = localSurfaceChange ? localSurfaceChange.current !== null : version.inlineSurface !== null;
    return {
        current: surfaceItems(currentList, currentHasLocal, surfaceName),
        version: surfaceItems(version.surfaceList, version.inlineSurface !== null, surfaceName),
    };
}

function surfaceItems(
    surfaceList: readonly unknown[],
    hasLocalSurface: boolean,
    surfaceName: (id: unknown) => string
): string[] {
    const surfaces = surfaceList.map(surfaceName);
    return hasLocalSurface ? [...surfaces, LOCAL_SURFACE_ITEM] : surfaces;
}

function asList(value: unknown): readonly unknown[] {
    return Array.isArray(value) ? value : [];
}
