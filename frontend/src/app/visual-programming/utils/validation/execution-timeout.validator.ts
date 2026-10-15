import { ValidatorFn } from '@angular/forms';
import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { formatDuration } from '../duration';

/**
 * Whether `seconds` is an execution timeout a python code may carry: a whole number of at least `minSeconds`.
 * There is no upper bound: the backend saves a longer timeout as its maximum, so a lowered maximum never blocks a save.
 */
export function isValidExecutionTimeout(seconds: unknown, minSeconds: number): boolean {
    return typeof seconds === 'number' && Number.isInteger(seconds) && seconds >= minSeconds;
}

/** The rule the minimum sets, worded for a message: `at least 5 s`. */
export function executionTimeoutMinimumRule(minSeconds: number): string {
    return `at least ${formatDuration(minSeconds)}`;
}

/** Whether a python code block has code: one without is not saved, and neither is its timeout. */
export function hasPythonCode(code: string | null | undefined): boolean {
    return !!code?.trim();
}

export function executionTimeoutValidator(minSeconds: number): ValidatorFn {
    return ({ value }) => (isValidExecutionTimeout(value, minSeconds) ? null : { executionTimeout: { minSeconds } });
}

/**
 * One message per node with an execution timeout the flow save must refuse. A panel commits its node to the flow
 * for a save even while its form is invalid, so an invalid timeout stops here. An absent one passes: the backend
 * applies its default. So does one on a table's pre- or post-computation without code, which the save drops.
 */
export function invalidExecutionTimeoutMessages(nodes: NodeModel[], minSeconds: number): string[] {
    return nodes
        .filter((node) =>
            executionTimeoutsOf(node).some(
                (seconds) => seconds !== undefined && !isValidExecutionTimeout(seconds, minSeconds)
            )
        )
        .map((node) => `"${node.node_name}" needs an execution timeout of ${executionTimeoutMinimumRule(minSeconds)}`);
}

function executionTimeoutsOf(node: NodeModel): (number | undefined)[] {
    switch (node.type) {
        case NodeType.PYTHON:
            return [node.data.execution_timeout];
        case NodeType.WEBHOOK_TRIGGER:
            return [node.data.python_code.execution_timeout];
        case NodeType.CLASSIFICATION_TABLE:
            return [node.data.table.pre_computation, node.data.table.post_computation].map((computation) =>
                hasPythonCode(computation?.code) ? computation?.execution_timeout : undefined
            );
        default:
            return [];
    }
}
