import { ShortcutParams } from '@shared/models';

import { EditorActionParam } from './editor-actions';

const PARAM_READERS: Readonly<
    Record<EditorActionParam, (params: ShortcutParams | undefined) => ShortcutParams | null>
> = {
    flow: (params) => {
        const flowId = flowIdOf(params);
        return flowId === null ? null : flowParams(flowId);
    },
};

export function readActionParams(param: EditorActionParam, params: ShortcutParams | undefined): ShortcutParams | null {
    return PARAM_READERS[param](params);
}

export function flowParams(flowId: number): ShortcutParams {
    return { flowId };
}

export function flowIdOf(params: ShortcutParams | null | undefined): number | null {
    const flowId = params?.['flowId'];
    return typeof flowId === 'number' && Number.isInteger(flowId) && flowId > 0 ? flowId : null;
}

export function sameParams(first: ShortcutParams | undefined, second: ShortcutParams | undefined): boolean {
    if (first === undefined || second === undefined) {
        return first === second;
    }
    const firstKeys = Object.keys(first);
    return (
        firstKeys.length === Object.keys(second).length &&
        firstKeys.every((key) => Object.hasOwn(second, key) && first[key] === second[key])
    );
}

export function isShortcutParams(value: unknown): value is ShortcutParams {
    return (
        typeof value === 'object' &&
        value !== null &&
        !Array.isArray(value) &&
        Object.values(value).every((entry) => typeof entry === 'number' || typeof entry === 'string')
    );
}
