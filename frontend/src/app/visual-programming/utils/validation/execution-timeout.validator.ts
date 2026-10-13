import {
    ExecutionTimeoutNodeType,
    isExecutionTimeoutNodeType,
    MIN_EXECUTION_TIMEOUT_MINUTES,
} from '../../core/constants/execution-timeout';
import { NodeModel } from '../../core/models/node.model';

type ExecutionTimeoutNodeModel = Extract<NodeModel, { type: ExecutionTimeoutNodeType }>;

/**
 * Whether the flow save may send `minutes`: a whole number of at least 1. A value above the sandbox ceiling
 * passes: the backend lowers it to the ceiling, so a lowered ceiling never blocks a save.
 */
function isSavableExecutionTimeout(minutes: number | null): boolean {
    return minutes != null && Number.isInteger(minutes) && minutes >= MIN_EXECUTION_TIMEOUT_MINUTES;
}

/**
 * One message per node whose execution timeout the flow save must refuse. A panel commits its node to the flow
 * for a save even while its form is invalid, so an emptied or fractional timeout stops here.
 */
export function invalidExecutionTimeoutMessages(nodes: NodeModel[]): string[] {
    return nodes
        .filter((node): node is ExecutionTimeoutNodeModel => isExecutionTimeoutNodeType(node.type))
        .filter((node) => !isSavableExecutionTimeout(node.execution_timeout))
        .map(
            (node) =>
                `"${node.node_name}" needs an execution timeout of at least ${MIN_EXECUTION_TIMEOUT_MINUTES} whole minute`
        );
}
