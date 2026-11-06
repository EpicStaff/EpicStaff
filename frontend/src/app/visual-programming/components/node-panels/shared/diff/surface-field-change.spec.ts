import { InlineSurface } from '../../../../core/models/task-node.model';
import { FieldChange, NodeDiffStatus } from '../../../../utils/diff';
import { NodeSurfaces, surfaceFieldChange } from './surface-field-change';

const diffOf = (fields: FieldChange[], status: NodeDiffStatus = 'changed') => ({
    status,
    fields,
    missingReferences: [],
});
const change = (field: string, current: unknown, version: unknown, status: FieldChange['status'] = 'changed') => ({
    path: field,
    field,
    status,
    current,
    version,
});
const SURFACE_NAMES: Record<number, string> = { 51: 'Sales', 52: 'Archive' };
const surfaceName = (id: unknown): string => SURFACE_NAMES[id as number] ?? `surface #${String(id)}`;

const LOCAL: InlineSurface = {
    instructions: 'Be brief',
    python_tools: [{ python_tool: 21, mode: 'allow' }],
    mcp_tools: [{ mcp_tool: 31, mode: 'deny' }],
    storage_items: [],
    knowledge: [],
};
const VERSION: NodeSurfaces = { surfaceList: [51], inlineSurface: LOCAL };
const VERSION_ITEMS = ['Sales', 'Local surface'];

describe('surfaceFieldChange', () => {
    it.each([
        {
            case: 'the surfaces picked, by name, or by id when not loaded',
            fields: [change('surface_list', [52, 53], [51])],
            current: ['Archive', 'surface #53', 'Local surface'],
        },
        {
            case: 'the local surface instructions changed: the same item, nothing struck',
            fields: [change('inline_surface.instructions', '', 'Be brief')],
            current: VERSION_ITEMS,
        },
        {
            case: 'the local surface tools changed: the same item, nothing struck',
            fields: [
                change('inline_surface.python_tools', [], [{ python_tool: 21, mode: 'allow' }]),
                change('inline_surface.mcp_tools', [{ mcp_tool: 32, mode: 'allow' }], [{ mcp_tool: 31, mode: 'deny' }]),
            ],
            current: VERSION_ITEMS,
        },
        {
            case: 'a local surface a restore adds',
            fields: [change('inline_surface', null, { instructions: 'Be brief' }, 'added')],
            current: ['Sales'],
        },
    ])('gives the canvas side with $case, the version side as the panel shows it', ({ fields, current }) => {
        expect(surfaceFieldChange(diffOf(fields), VERSION, surfaceName)).toEqual({ current, version: VERSION_ITEMS });
    });

    it('gives the canvas local surface as one item when a restore removes it', () => {
        const canvasLocal = { instructions: 'Old', python_tools: [], mcp_tools: [{ mcp_tool: 31, mode: 'deny' }] };

        expect(
            surfaceFieldChange(
                diffOf([change('inline_surface', canvasLocal, null, 'deleted')]),
                { surfaceList: [51], inlineSurface: null },
                surfaceName
            )
        ).toEqual({ current: ['Sales', 'Local surface'], version: ['Sales'] });
    });

    it('gives nothing when no surface field changed, on a node not changed, or with no diff', () => {
        const surfacesChange = change('surface_list', [52], [51]);

        expect(surfaceFieldChange(diffOf([change('node_name', 'a', 'b')]), VERSION, surfaceName)).toBeNull();
        expect(surfaceFieldChange(diffOf([surfacesChange], 'deleted'), VERSION, surfaceName)).toBeNull();
        expect(surfaceFieldChange(null, VERSION, surfaceName)).toBeNull();
    });
});
