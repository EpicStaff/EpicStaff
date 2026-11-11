import { KeyedItemChange, keyedItemChanges, UnionNodeDiffState } from '../../../../utils/diff';
import { DiffFieldMarkChange } from '../../../diff-field-mark/diff-field-mark.component';

/** How a task row (a version task) shows what a restore does to it: marked when changed, framed green when added. */
export interface AgentTaskRowMark {
    added: boolean;
    /** The row's changed cells on the canvas and in the version; `null` for a row a restore does not change. */
    change: DiffFieldMarkChange | null;
    /** The row's tooltip and description instead of the values: the columns a restore changes. */
    hint: string | null;
}

/** A row a restore keeps as it is. */
export const KEPT_AGENT_TASK_ROW: AgentTaskRowMark = { added: false, change: null, hint: null };

/** A canvas task the version does not have (a restore removes it), as its row shows it. */
export interface RemovedAgentTask {
    /** Its position on the canvas, as the row number shows it. */
    position: string;
    name: string;
    instructions: string;
    /** As the Output Schema cell shows it: empty for no schema. */
    outputSchema: string;
    /** The canvas positions of the tasks it takes as context. */
    contextPositions: number[];
}

/** What a restore does to the rows of an Agent node's tasks table. */
export interface AgentTaskRowChanges {
    /** By row, in the version's order (the rows the table shows). */
    rows: AgentTaskRowMark[];
    /** The canvas tasks a restore removes, in their canvas order. */
    removed: RemovedAgentTask[];
}

/** The table's columns, by the task fields the diff compares, in the table's order. */
const COLUMN_BY_FIELD: Readonly<Record<string, string>> = {
    name: 'Name',
    instructions: 'Instructions',
    output_schema: 'Output Schema',
    context_tasks: 'Task Context',
};

/**
 * What a restore does to each task row of an Agent node (Changes tab of a version preview). Tasks run in order, so the
 * diff pairs them by position: a moved task shows as changed rows. `null` when the node shows no field marks or no
 * task changed.
 */
export function agentTaskRowChanges(diff: UnionNodeDiffState | null, rowCount: number): AgentTaskRowChanges | null {
    const items = keyedItemChanges(diff, 'tasks');
    if (items === null) return null;
    const byPosition = new Map(items.map((item) => [item.key, item]));
    const rows = Array.from({ length: rowCount }, (_, index): AgentTaskRowMark => {
        const item = byPosition.get(String(index + 1));
        if (!item || item.status === 'deleted') return KEPT_AGENT_TASK_ROW;
        if (item.status === 'added') return { ...KEPT_AGENT_TASK_ROW, added: true };
        return { added: false, change: item, hint: `Changed columns: ${changedColumns(item).join(', ')}.` };
    });
    const removed = items.filter((item) => item.status === 'deleted').map(removedTask);
    return { rows, removed };
}

/** A task whose value is not an object changes as a whole: every column. */
function changedColumns(item: KeyedItemChange): string[] {
    const fields = item.fields.length > 0 ? item.fields : Object.keys(COLUMN_BY_FIELD);
    return Object.entries(COLUMN_BY_FIELD)
        .filter(([field]) => fields.includes(field))
        .map(([, column]) => column);
}

function removedTask(item: KeyedItemChange): RemovedAgentTask {
    const task = (item.current ?? {}) as Partial<Record<string, unknown>>;
    const schema = task['output_schema'];
    const hasSchema = schema !== null && typeof schema === 'object' && Object.keys(schema).length > 0;
    return {
        position: item.key,
        name: typeof task['name'] === 'string' ? task['name'] : '',
        instructions: typeof task['instructions'] === 'string' ? task['instructions'] : '',
        outputSchema: hasSchema ? JSON.stringify(schema, null, 2) : '',
        contextPositions: Array.isArray(task['context_tasks']) ? (task['context_tasks'] as number[]) : [],
    };
}
