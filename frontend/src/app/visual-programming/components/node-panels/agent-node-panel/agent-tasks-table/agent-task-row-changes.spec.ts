import { FieldChange, NodeDiffStatus } from '../../../../utils/diff';
import { agentTaskRowChanges } from './agent-task-row-changes';

const diffOf = (fields: FieldChange[], status: NodeDiffStatus = 'changed') => ({
    status,
    fields,
    missingReferences: [],
});
const taskFieldChange = (position: number, field: string, current: unknown, version: unknown): FieldChange => ({
    path: `tasks[${position}].${field}`,
    field: `tasks[].${field}`,
    status: 'changed',
    current,
    version,
});
const REVIEW = { name: 'Review', instructions: 'Check it', output_schema: { type: 'object' }, context_tasks: [1, 2] };

describe('agentTaskRowChanges', () => {
    it('marks each version row a restore changes or adds, by position, and lists the canvas rows it removes', () => {
        const changes = agentTaskRowChanges(
            diffOf([
                taskFieldChange(2, 'context_tasks', [1], []),
                taskFieldChange(2, 'name', 'Draft', 'Write'),
                { path: 'tasks[3]', field: 'tasks[]', status: 'added', current: null, version: REVIEW },
                { path: 'tasks[4]', field: 'tasks[]', status: 'deleted', current: REVIEW, version: null },
            ]),
            3
        );

        expect(changes).toEqual({
            rows: [
                { added: false, change: null, hint: null },
                {
                    added: false,
                    change: expect.objectContaining({
                        current: { context_tasks: [1], name: 'Draft' },
                        version: { context_tasks: [], name: 'Write' },
                    }),
                    // In the table's column order, whatever the diff's.
                    hint: 'Changed columns: Name, Task Context.',
                },
                { added: true, change: null, hint: null },
            ],
            removed: [
                {
                    position: '4',
                    name: 'Review',
                    instructions: 'Check it',
                    outputSchema: '{\n  "type": "object"\n}',
                    contextPositions: [1, 2],
                },
            ],
        });
    });

    it.each([
        { column: 'Instructions', field: 'instructions' },
        { column: 'Output Schema', field: 'output_schema' },
    ])('names the $column column for a change of $field', ({ column, field }) => {
        const changes = agentTaskRowChanges(diffOf([taskFieldChange(1, field, 'old', 'new')]), 1);

        expect(changes?.rows[0]).toEqual(expect.objectContaining({ hint: `Changed columns: ${column}.` }));
    });

    it('shows a removed task without a schema as an empty Output Schema cell', () => {
        const noSchema = { ...REVIEW, output_schema: {}, context_tasks: [] };
        const changes = agentTaskRowChanges(
            diffOf([{ path: 'tasks[1]', field: 'tasks[]', status: 'deleted', current: noSchema, version: null }]),
            0
        );

        expect(changes?.removed).toEqual([
            { position: '1', name: 'Review', instructions: 'Check it', outputSchema: '', contextPositions: [] },
        ]);
    });

    it('gives nothing when no task changed, on a node not changed, or with no diff', () => {
        const nameChange = taskFieldChange(1, 'name', 'Draft', 'Write');

        expect(agentTaskRowChanges(diffOf([{ ...nameChange, path: 'node_name', field: 'node_name' }]), 1)).toBeNull();
        expect(agentTaskRowChanges(diffOf([nameChange], 'added'), 1)).toBeNull();
        expect(agentTaskRowChanges(null, 1)).toBeNull();
    });
});
