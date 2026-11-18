import { SystemOneQuestion } from '@shared/models';

/** Python's hard keywords, as the backend checks them with `keyword.iskeyword`. */
const PYTHON_KEYWORDS: ReadonlySet<string> = new Set([
    'False',
    'None',
    'True',
    'and',
    'as',
    'assert',
    'async',
    'await',
    'break',
    'class',
    'continue',
    'def',
    'del',
    'elif',
    'else',
    'except',
    'finally',
    'for',
    'from',
    'global',
    'if',
    'import',
    'in',
    'is',
    'lambda',
    'nonlocal',
    'not',
    'or',
    'pass',
    'raise',
    'return',
    'try',
    'while',
    'with',
    'yield',
]);

const PYTHON_IDENTIFIER = /^[\p{L}\p{Nl}_][\p{L}\p{Nl}\p{Mn}\p{Mc}\p{Nd}\p{Pc}]*$/u;

export const MAX_CHOICE_OPTIONS = 255;
export const MAX_SCORE_LEVELS = 10;
export const MAX_SYSTEM_ONE_QUESTIONS = 400;

const QUESTION_KEYS: ReadonlySet<string> = new Set(['type', 'instructions', 'criteria']);

/** A question is read as `answers.<name>` in conditions, so its name must be a Python identifier, not starting with `_`. Mirrors `src/shared/models/system_one.py`. */
export function isValidQuestionName(name: string): boolean {
    return PYTHON_IDENTIFIER.test(name) && !PYTHON_KEYWORDS.has(name) && !name.startsWith('_');
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function areStrings(values: unknown[]): boolean {
    return values.every((value) => typeof value === 'string');
}

/** True when the backend accepts the question under this name: valid name, instructions, and criteria complete for its type. */
export function isCompleteQuestion(name: string, question: unknown): question is SystemOneQuestion {
    if (!isValidQuestionName(name) || !isRecord(question)) return false;
    if (!Object.keys(question).every((key) => QUESTION_KEYS.has(key))) return false;
    if (typeof question['instructions'] !== 'string' || question['instructions'].trim() === '') return false;

    const criteria = question['criteria'];
    switch (question['type']) {
        case 'noul':
            return (
                criteria == null ||
                (isRecord(criteria) &&
                    Object.keys(criteria).every((key) => key === 'true' || key === 'false') &&
                    areStrings(Object.values(criteria)))
            );
        case 'choice': {
            if (!isRecord(criteria)) return false;
            const options = Object.values(criteria);
            return options.length >= 2 && options.length <= MAX_CHOICE_OPTIONS && areStrings(options);
        }
        case 'score':
            return (
                Array.isArray(criteria) &&
                criteria.length >= 2 &&
                criteria.length <= MAX_SCORE_LEVELS &&
                areStrings(criteria)
            );
        default:
            return false;
    }
}
