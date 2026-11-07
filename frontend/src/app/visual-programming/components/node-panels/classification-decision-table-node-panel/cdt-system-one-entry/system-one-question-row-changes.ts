import { SystemOneQuestion } from '@shared/models';

import { isSameValue, mapFieldRowChanges, MapKeyChange, UnionNodeDiffState } from '../../../../utils/diff';
import { DiffFieldMarkChange } from '../../../diff-field-mark/diff-field-mark.component';

/** How a question of a System One entry (a version question) shows what a restore does to it. */
export interface QuestionRowMark {
    added: boolean;
    /** The question on the canvas and in the version; `null` for a question a restore does not change. */
    change: DiffFieldMarkChange | null;
    /** The row's tooltip and description instead of the values: the parts of the question a restore changes. */
    hint: string | null;
}

/** A question a restore keeps as it is. */
export const KEPT_QUESTION_ROW: QuestionRowMark = { added: false, change: null, hint: null };

/** A canvas question the version does not have (a restore removes it), as its row shows it. */
export interface RemovedQuestion {
    name: string;
    type: string;
    instructions: string;
}

/** What a restore does to the questions of one System One entry. */
export interface QuestionRowChanges {
    /** By question name; a question without an entry is kept. */
    rows: ReadonlyMap<string, QuestionRowMark>;
    /** The canvas questions a restore removes. */
    removed: RemovedQuestion[];
}

/** The words of the question form for its criteria, by question type. */
const CRITERIA_LABEL: Readonly<Record<SystemOneQuestion['type'], string>> = {
    noul: 'True and false meanings',
    choice: 'Options',
    score: 'Levels',
};

/**
 * What a restore does to each question of the System One entry `promptKey` (Changes tab of a version preview). The
 * diff compares the questions as one value, so they are paired here by name. `null` when the node shows no field
 * marks or the questions are unchanged.
 */
export function systemOneQuestionRowChanges(
    diff: UnionNodeDiffState | null,
    promptKey: string
): QuestionRowChanges | null {
    const changes = mapFieldRowChanges(diff, 'prompts[].questions', `prompts[key=${promptKey}].questions`);
    if (changes === null) return null;
    const rows = new Map<string, QuestionRowMark>();
    for (const change of changes) {
        if (change.status === 'added') rows.set(change.key, { ...KEPT_QUESTION_ROW, added: true });
        if (change.status === 'changed') {
            rows.set(change.key, {
                added: false,
                change,
                hint: `Changed fields: ${changedParts(change).join(', ')}.`,
            });
        }
    }
    const removed = changes.filter((change) => change.status === 'deleted').map(removedQuestion);
    return { rows, removed };
}

/**
 * The parts of a question that differ, in the form's order, the criteria named as the version's question type names
 * them. A question that is not an object changes as a whole: every part.
 */
function changedParts(change: MapKeyChange): string[] {
    const current = asQuestion(change.current);
    const version = asQuestion(change.version);
    const versionType = version['type'];
    const criteria = isQuestionType(versionType) ? CRITERIA_LABEL[versionType] : 'Criteria';
    const parts = [
        { label: 'Type', changed: current['type'] !== version['type'] },
        { label: 'Instructions', changed: !isSameValue(current['instructions'], version['instructions']) },
        { label: criteria, changed: !isSameValue(current['criteria'], version['criteria']) },
    ];
    const changed = parts.filter((part) => part.changed);
    return (changed.length > 0 ? changed : parts).map((part) => part.label);
}

function removedQuestion(change: MapKeyChange): RemovedQuestion {
    const question = asQuestion(change.current);
    return {
        name: change.key,
        type: typeof question['type'] === 'string' ? question['type'] : '',
        instructions: typeof question['instructions'] === 'string' ? question['instructions'] : '',
    };
}

function isQuestionType(type: unknown): type is SystemOneQuestion['type'] {
    return typeof type === 'string' && Object.hasOwn(CRITERIA_LABEL, type);
}

function asQuestion(value: unknown): Partial<Record<string, unknown>> {
    return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}
