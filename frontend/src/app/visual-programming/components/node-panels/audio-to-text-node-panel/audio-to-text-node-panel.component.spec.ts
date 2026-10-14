import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { InputNumberComponent } from '@shared/components';
import { NodeType } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { AudioToTextNodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { SandboxLimitsStorageService } from '../../../services/sandbox-limits-storage.service';
import {
    provideLoadedSandboxLimits,
    TEST_MAX_EXECUTION_TIMEOUT_MINUTES,
} from '../../../utils/testing/sandbox-limits.testing';
import { InputMapComponent } from '../../input-map/input-map.component';
import { AudioToTextNodePanelComponent } from './audio-to-text-node-panel.component';

function node(executionTimeout: number | null): AudioToTextNodeModel {
    return {
        id: 'audio-to-text-1',
        backendId: 7,
        type: NodeType.AUDIO_TO_TEXT,
        node_name: 'Audio To Text #1',
        data: undefined,
        execution_timeout: executionTimeout,
        position: { x: 0, y: 0 },
        ports: null,
        color: '',
        icon: '',
        size: { width: 200, height: 100 },
        input_map: {},
        output_variable_path: null,
    } as unknown as AudioToTextNodeModel;
}

describe('AudioToTextNodePanelComponent execution timeout', () => {
    let fixture: ComponentFixture<AudioToTextNodePanelComponent>;

    function open(executionTimeout: number | null): AudioToTextNodePanelComponent {
        TestBed.configureTestingModule({
            providers: [
                provideLoadedSandboxLimits(),
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        // The input map needs the whole flow editor; it plays no part in the timeout.
        TestBed.overrideComponent(AudioToTextNodePanelComponent, {
            remove: { imports: [InputMapComponent] },
            add: { schemas: [NO_ERRORS_SCHEMA] },
        });
        fixture = TestBed.createComponent(AudioToTextNodePanelComponent);
        fixture.componentRef.setInput('node', node(executionTimeout));
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    function timeoutInput(): InputNumberComponent {
        return fixture.debugElement.query(By.css('app-execution-timeout-field app-input-number'))
            .componentInstance as InputNumberComponent;
    }

    it('shows the stored timeout, up to the ceiling', () => {
        open(60);

        expect(timeoutInput().value()).toBe(60);
        expect(timeoutInput().max()).toBe(TEST_MAX_EXECUTION_TIMEOUT_MINUTES);
    });

    it('shows a node saved before nodes had a timeout at the ceiling', () => {
        open(null);

        expect(timeoutInput().value()).toBe(TEST_MAX_EXECUTION_TIMEOUT_MINUTES);
    });

    it('puts the edited timeout on the node it saves', () => {
        const panel = open(60);

        panel.form.patchValue({ execution_timeout: 15 });

        expect(panel.onSaveSilently()?.execution_timeout).toBe(15);
    });

    it('keeps a timeout saved under a higher ceiling, with a warning, and closes with it and the other edits', () => {
        const aboveCeiling = TEST_MAX_EXECUTION_TIMEOUT_MINUTES + 30;
        const panel = open(aboveCeiling);

        expect(panel.form.valid).toBe(true);
        expect(timeoutInput().isAboveWarning()).toBe(true);
        panel.form.patchValue({ output_variable_path: 'variables.text' });
        const saved = panel.onSave();

        expect(saved?.execution_timeout).toBe(aboveCeiling);
        expect(saved?.output_variable_path).toBe('variables.text');
    });

    it('caps an edit of the timeout at the ceiling', () => {
        const panel = open(60);

        panel.form.patchValue({ execution_timeout: TEST_MAX_EXECUTION_TIMEOUT_MINUTES + 1 });

        expect(panel.onSave()?.execution_timeout).toBe(TEST_MAX_EXECUTION_TIMEOUT_MINUTES);
    });

    it('keeps working after the limits are cleared (logout, organization switch) while it is open', () => {
        const panel = open(60);
        const form = panel.form;

        TestBed.inject(SandboxLimitsStorageService).clear();
        TestBed.tick();
        fixture.detectChanges();

        expect(panel.form).toBe(form);
        expect(panel.onSave()?.execution_timeout).toBe(60);
    });
});
