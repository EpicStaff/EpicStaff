import { v4 as uuidv4 } from 'uuid';

import { PythonNode } from '../../../../pages/flows-page/components/flow-visual-programming/models/python-node.model';
import { NodeType } from '../../../core/enums/node-type';
import { PythonNodeModel } from '../../../core/models/node.model';
import { mapNodeDtoMetadataToFlowNodeMetadata } from '../node-dto-metadata-to-flow-metadata.mapper';

export function mapPythonNodeToModel(pn: PythonNode): PythonNodeModel {
    const ui = mapNodeDtoMetadataToFlowNodeMetadata(pn.metadata, NodeType.PYTHON);
    return {
        id: uuidv4(),
        backendId: pn.id,
        type: NodeType.PYTHON,
        node_name: pn.node_name,
        nodeNumber: ui.nodeNumber,
        data: {
            name: pn.node_name,
            libraries: pn.python_code.libraries,
            code: pn.python_code.code,
            entrypoint: pn.python_code.entrypoint,
            use_storage: pn.use_storage ?? false,
        },
        position: ui.position,
        ports: null,
        color: ui.color,
        icon: ui.icon,
        input_map: pn.input_map ?? {},
        output_variable_path: pn.output_variable_path,
        stream_config: pn.stream_config ?? {},
        size: ui.size,
    };
}
