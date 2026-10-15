import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { PythonNodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { PythonNodePanelComponent } from './python-node-panel.component';

const pythonNode = {
    id: 'python-1',
    backendId: null,
    type: NodeType.PYTHON,
    node_name: 'Python #1',
    python_code_id: null,
    data: {
        code: 'def main(): pass',
        entrypoint: 'main',
        libraries: [],
        secret_ids: [7],
        secret_names: ['STRIPE_KEY'],
    },
    test_input: {},
    position: { x: 0, y: 0 },
    ports: null,
    color: '',
    icon: '',
    size: { width: 200, height: 100 },
    input_map: {},
    output_variable_path: null,
} as unknown as PythonNodeModel;

// A user with Secrets:Use who may edit flows: any read-only here comes from the preview.
function create(isPreview: boolean): PythonNodePanelComponent {
    TestBed.configureTestingModule({
        providers: [
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PermissionsService, useValue: { can: () => true, canEditSecrets: () => true } },
        ],
    });
    TestBed.overrideComponent(PythonNodePanelComponent, { set: { template: '', imports: [] } });
    const fixture = TestBed.createComponent(PythonNodePanelComponent);
    fixture.componentRef.setInput('node', pythonNode);
    fixture.detectChanges();
    return fixture.componentInstance;
}

describe('PythonNodePanelComponent secrets', () => {
    it('is read-only in a version preview and shows the names saved on the node', () => {
        const panel = create(true);

        expect(panel.canEditSecrets()).toBe(false);
        expect(panel.secretNames()).toEqual(['STRIPE_KEY']);
        expect(panel.secretsTooltip()).toBe('Secrets assigned to this Python code.');
    });

    it('stays editable in the live editor for a user with Secrets:Use', () => {
        expect(create(false).canEditSecrets()).toBe(true);
    });
});
