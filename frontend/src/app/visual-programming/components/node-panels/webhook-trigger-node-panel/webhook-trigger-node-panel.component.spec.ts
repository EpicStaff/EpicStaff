import { NgTemplateOutlet } from '@angular/common';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { SecretsStorageService } from '@shared/services';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { RuffDiagnosticsService } from '../../../../shared/ruff-linter/services/ruff-diagnostics.service';
import { RuffWasmService } from '../../../../shared/ruff-linter/services/ruff-wasm.service';
import { CodeEditorComponent } from '../../../../user-settings-page/tools/custom-tool-editor/code-editor/code-editor.component';
import { WebhookTriggerNodeModel } from '../../../core/models/node.model';
import { GetWebhookTriggerNodeRequest } from '../../../core/models/webhook-trigger';
import { mapWebhookTriggerNodeToModel } from '../../../utils/load/nodes/webhook-trigger-node.mapper';
import { formatTestPayload } from '../../../utils/test-run';
import {
    INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE,
    TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE,
    TriggerTestPayloadState,
} from '../shared/test-payload-section/trigger-test-payload.state';
import { WebhookTriggerNodePanelComponent } from './webhook-trigger-node-panel.component';

const SAVED_PAYLOAD = { order: { id: '104' } };

const DTO: GetWebhookTriggerNodeRequest = {
    id: 21,
    graph: 1,
    node_name: 'Webhook Trigger #1',
    python_code: { id: 5, libraries: [], code: 'def main(trigger_payload): pass', entrypoint: 'main' },
    input_map: {},
    output_variable_path: null,
    webhook_trigger_path: '',
    metadata: {},
    webhook_trigger: null,
    test_payload: SAVED_PAYLOAD,
};

/** The template-facing members the panel's test payload editor binds to. */
interface TestPayloadPanel {
    testPayload: TriggerTestPayloadState;
    onTestPayloadTextChange(text: string): void;
}

describe('WebhookTriggerNodePanelComponent test payload', () => {
    let fixture: ComponentFixture<WebhookTriggerNodePanelComponent>;
    let panel: WebhookTriggerNodePanelComponent;
    let toast: Record<string, ReturnType<typeof vi.fn>>;

    beforeEach(() => {
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ToastService, useValue: toast },
                {
                    provide: PermissionsService,
                    useValue: { can: () => true, canAny: () => true, canEditSecrets: () => true },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: signal([]), namesForIds: () => [], getSecrets: vi.fn() },
                },
            ],
        });
        // The editors (Monaco) and shared controls are not under test: only the panel's state wiring is.
        TestBed.overrideComponent(WebhookTriggerNodePanelComponent, { set: { template: '', imports: [] } });
        fixture = TestBed.createComponent(WebhookTriggerNodePanelComponent);
        panel = fixture.componentInstance;
        fixture.componentRef.setInput('node', mapWebhookTriggerNodeToModel(DTO));
        fixture.detectChanges();
    });

    function editor(): TestPayloadPanel {
        return panel as unknown as TestPayloadPanel;
    }

    function savedTestPayload(): WebhookTriggerNodeModel['data']['test_payload'] {
        return panel.onSaveSilently()!.data.test_payload;
    }

    it('shows the saved payload and saves it unchanged while not edited', () => {
        expect(editor().testPayload.text()).toBe(formatTestPayload(SAVED_PAYLOAD));
        expect(panel.isDirty()).toBe(false);
        expect(savedTestPayload()).toEqual(SAVED_PAYLOAD);
    });

    it('saves an edited payload that parses', () => {
        editor().onTestPayloadTextChange('{"order": {"id": "200"}}');

        expect(panel.isDirty()).toBe(true);
        expect(savedTestPayload()).toEqual({ order: { id: '200' } });
    });

    it('stays dirty with an invalid edit, keeps the saved payload and says it was not saved', () => {
        editor().onTestPayloadTextChange('{"order": ');
        expect(panel.isDirty()).toBe(true);

        const savedNode = panel.onSave();

        expect(savedNode!.data.test_payload).toEqual(SAVED_PAYLOAD);
        expect(toast['warning']).toHaveBeenCalledWith(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
        // Still not saved: the panel keeps counting it as an unsaved change.
        expect(panel.isDirty()).toBe(true);
    });

    it('says an invalid payload edit was not saved on Ctrl+S as well', () => {
        panel.form.patchValue({ node_name: 'Renamed' });
        editor().onTestPayloadTextChange('{"order": ');

        const savedNode = panel.onSaveSilently();

        expect(savedNode!.node_name).toBe('Renamed');
        expect(savedNode!.data.test_payload).toEqual(SAVED_PAYLOAD);
        expect(toast['warning']).toHaveBeenCalledTimes(1);
        expect(toast['warning']).toHaveBeenCalledWith(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
        expect(panel.isDirty()).toBe(true);
    });

    it('is clean again once an invalid edit is fixed back to the saved payload', () => {
        editor().onTestPayloadTextChange('nope');
        editor().onTestPayloadTextChange(JSON.stringify(SAVED_PAYLOAD));

        expect(panel.isDirty()).toBe(false);
    });

    it('does not warn when a valid edit is saved', () => {
        editor().onTestPayloadTextChange('{}');

        panel.onSaveSilently();
        panel.onSave();

        expect(toast['warning']).not.toHaveBeenCalled();
    });

    describe('while the form is invalid', () => {
        const EDITED_PAYLOAD = { order: { id: '200' } };

        function invalidateForm(): void {
            panel.form.patchValue({ node_name: '', libraries: 'requests' });
            expect(panel.form.invalid).toBe(true);
        }

        it('onSave (close, Esc, autosave) saves a valid payload edit alone onto the last saved node', () => {
            const lastSavedNode = panel.node();
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            const savedNode = panel.onSave();

            expect(savedNode).toEqual({
                ...lastSavedNode,
                data: { ...lastSavedNode.data, test_payload: EDITED_PAYLOAD },
            });
            expect(toast['warning']).toHaveBeenCalledTimes(1);
            expect(toast['warning']).toHaveBeenCalledWith(TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE);
            // The other edits are still unsaved; the payload is not saved again.
            expect(panel.isDirty()).toBe(true);
            expect(panel.onSave()).toBeNull();
            expect(toast['warning']).toHaveBeenCalledTimes(1);
        });

        it('onSaveSilently (Ctrl+S) saves nothing and leaves every edit as it was', () => {
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            expect(panel.onSaveSilently()).toBeNull();

            expect(toast['warning']).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(true);
            expect(panel.form.value).toEqual(expect.objectContaining({ node_name: '', libraries: 'requests' }));
            expect(editor().testPayload.text()).toBe(JSON.stringify(EDITED_PAYLOAD));
            expect(editor().testPayload.isEdited()).toBe(true);
            // The payload edit is still unsaved: closing the panel saves it.
            expect(panel.onSave()!.data.test_payload).toEqual(EDITED_PAYLOAD);
        });

        it('shows no toast when the payload was the only edit', () => {
            fixture.componentRef.setInput('node', mapWebhookTriggerNodeToModel({ ...DTO, node_name: '' }));
            fixture.detectChanges();
            expect(panel.form.invalid).toBe(true);
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            panel.onSave();

            expect(toast['warning']).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(false);
        });

        it('saves nothing for payload text that is not valid JSON', () => {
            invalidateForm();
            editor().onTestPayloadTextChange('{"order": ');

            expect(panel.onSave()).toBeNull();
            expect(panel.onSaveSilently()).toBeNull();
            expect(toast['warning']).not.toHaveBeenCalled();
        });

        it('saves nothing when the payload was not edited', () => {
            invalidateForm();

            expect(panel.onSave()).toBeNull();
            expect(panel.onSaveSilently()).toBeNull();
            expect(toast['warning']).not.toHaveBeenCalled();
        });

        it('saves nothing when the payload was edited back to the saved one', () => {
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(SAVED_PAYLOAD));

            expect(panel.onSave()).toBeNull();
        });

        it('saves the whole node, payload included, once the form is valid again', () => {
            invalidateForm();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));
            panel.onSave();

            panel.form.patchValue({ node_name: 'Fixed name' });
            const savedNode = panel.onSave();

            expect(savedNode!.node_name).toBe('Fixed name');
            expect(savedNode!.data.python_code.libraries).toEqual(['requests']);
            expect(savedNode!.data.test_payload).toEqual(EDITED_PAYLOAD);
            expect(panel.isDirty()).toBe(false);
        });
    });
});

describe('WebhookTriggerNodePanelComponent code editor header', () => {
    let fixture: ComponentFixture<WebhookTriggerNodePanelComponent>;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ToastService, useValue: {} },
                {
                    provide: PermissionsService,
                    useValue: { can: () => true, canAny: () => true, canEditSecrets: () => true },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: signal([]), namesForIds: () => [], getSecrets: vi.fn() },
                },
                { provide: RuffWasmService, useValue: { check: () => Promise.resolve([]) } },
                { provide: RuffDiagnosticsService, useValue: { setMarkers: () => {}, hasSyntaxErrors: () => false } },
            ],
        });
        // Real panel template, but only the code editor is a real (empty, Monaco-free) component: the
        // other controls render as unknown elements.
        TestBed.overrideComponent(WebhookTriggerNodePanelComponent, {
            set: { imports: [NgTemplateOutlet, CodeEditorComponent], schemas: [NO_ERRORS_SCHEMA] },
        });
        TestBed.overrideComponent(CodeEditorComponent, { set: { template: '', imports: [] } });
        fixture = TestBed.createComponent(WebhookTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', mapWebhookTriggerNodeToModel(DTO));
    });

    function codeEditors(): CodeEditorComponent[] {
        return fixture.debugElement
            .queryAll(By.directive(CodeEditorComponent))
            .map((editorElement) => editorElement.componentInstance as CodeEditorComponent);
    }

    it('uses the JSON-style header for the code card of the small panel', () => {
        fixture.detectChanges();

        const editors = codeEditors();
        expect(editors).toHaveLength(1);
        expect(editors[0].compactHeader()).toBe(true);
    });

    it('uses the JSON-style header for the code editor in the big pane of the expanded panel', () => {
        fixture.componentRef.setInput('isExpanded', true);
        fixture.detectChanges();

        const editors = codeEditors();
        expect(editors).toHaveLength(1);
        expect(editors[0].expandLabel()).toBe('Swap with test payload');
        expect(editors[0].compactHeader()).toBe(true);
    });

    it('uses the JSON-style header for the code card moved to the left column of the expanded panel', () => {
        fixture.componentRef.setInput('isExpanded', true);
        (fixture.componentInstance as unknown as { expandPane(pane: 'payload'): void }).expandPane('payload');
        fixture.detectChanges();

        const editors = codeEditors();
        expect(editors).toHaveLength(1);
        expect(editors[0].editorHeight()).toBe(220);
        expect(editors[0].compactHeader()).toBe(true);
    });
});
