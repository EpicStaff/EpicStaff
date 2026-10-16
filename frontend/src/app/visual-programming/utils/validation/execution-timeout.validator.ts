import { executionTimeoutMinimumRule, isValidExecutionTimeout } from '@shared/form-validators';
import { NodeType } from '@shared/models';

import { NodeModel } from '../../core/models/node.model';
import { isPythonCodeBlockSaved } from '../save/cdt-python-code-block';

/**
 * One message per node with an execution timeout the flow save must refuse. A panel commits its node to the flow
 * for a save even while its form is invalid, so an invalid timeout stops here. An absent one passes: the backend
 * applies its default. So does one on a table's pre- or post-computation the save drops (no code, no secrets).
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
                isPythonCodeBlockSaved(computation?.code, computation?.secret_ids)
                    ? computation?.execution_timeout
                    : undefined
            );
        default:
            return [];
    }
}
