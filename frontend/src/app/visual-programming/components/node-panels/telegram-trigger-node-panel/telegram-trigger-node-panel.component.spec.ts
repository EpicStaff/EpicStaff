import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA, NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ConfirmationDialogService, ConfirmationResult, JsonEditorComponent } from '@shared/components';
import { SecretsStorageService } from '@shared/services';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { GetTelegramTriggerNodeRequest, TelegramTriggerNodeField } from '../../../core/models/telegram-trigger.model';
import { FlowTestRunService } from '../../../services/flow-test-run.service';
import { mapTelegramTriggerNodeToModel } from '../../../utils/load/nodes/telegram-trigger-node.mapper';
import {
    buildTelegramSamplePayload,
    formatTestPayload,
    TELEGRAM_NO_FIELDS_SELECTED_MESSAGE,
} from '../../../utils/test-run';
import { TestPayloadSectionComponent } from '../shared/test-payload-section/test-payload-section.component';
import {
    INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE,
    TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE,
    TriggerTestPayloadState,
} from '../shared/test-payload-section/trigger-test-payload.state';
import {
    INSERT_EXAMPLE_NO_FIELDS_REASON,
    INSERT_EXAMPLE_PAYLOAD_ICON,
    INSERT_EXAMPLE_PAYLOAD_LABEL,
    TelegramTriggerNodePanelComponent,
} from './telegram-trigger-node-panel.component';

const MESSAGE_ID: TelegramTriggerNodeField = {
    id: 1,
    parent: 'message',
    field_name: 'message_id',
    variable_path: 'variables.id',
};
const MESSAGE_TEXT: TelegramTriggerNodeField = {
    id: 2,
    parent: 'message',
    field_name: 'text',
    variable_path: 'variables.text',
};

function telegramNode(testPayload: Record<string, unknown> = {}): TelegramTriggerNodeModel {
    const dto: GetTelegramTriggerNodeRequest = {
        id: 31,
        graph: 1,
        node_name: 'Telegram Trigger #1',
        telegram_bot_api_key_secret_id: 7,
        fields: [MESSAGE_ID],
        metadata: {},
        webhook_trigger: null,
        test_payload: testPayload,
    };
    return mapTelegramTriggerNodeToModel(dto);
}

/** The template-facing members the panel's test payload editor binds to. */
interface TestPayloadPanel {
    testPayload: TriggerTestPayloadState;
    onTestPayloadTextChange(text: string): void;
    insertExampleDisabledReason(): string | null;
    insertExamplePayload(): void;
}

describe('TelegramTriggerNodePanelComponent test payload', () => {
    let fixture: ComponentFixture<TelegramTriggerNodePanelComponent>;
    let panel: TelegramTriggerNodePanelComponent;
    let toast: Record<string, ReturnType<typeof vi.fn>>;
    let canUpdateFlows: boolean;
    let dialogResult: TelegramTriggerNodeField[] | undefined;
    let confirmResult: ConfirmationResult;
    let confirm: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() };
        canUpdateFlows = true;
        dialogResult = undefined;
        confirmResult = true;
        confirm = vi.fn(() => of(confirmResult));
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ToastService, useValue: toast },
                {
                    provide: PermissionsService,
                    useValue: { can: () => canUpdateFlows, canAny: () => canUpdateFlows },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: signal([]), maskTail: () => '', getSecrets: () => of([]) },
                },
                { provide: Dialog, useValue: { open: () => ({ closed: of(dialogResult) }) } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
            ],
        });
        // The JSON editor (Monaco) and shared controls are not under test: only the panel's state wiring is.
        TestBed.overrideComponent(TelegramTriggerNodePanelComponent, { set: { template: '', imports: [] } });
    });

    function open(node: TelegramTriggerNodeModel): void {
        fixture = TestBed.createComponent(TelegramTriggerNodePanelComponent);
        panel = fixture.componentInstance;
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
    }

    function editor(): TestPayloadPanel {
        return panel as unknown as TestPayloadPanel;
    }

    function sampleText(fields: TelegramTriggerNodeField[]): string {
        return formatTestPayload(buildTelegramSamplePayload(fields));
    }

    it('seeds a sample of the picked fields but never saves an unedited seed', () => {
        open(telegramNode());

        expect(editor().testPayload.text()).toBe(sampleText([MESSAGE_ID]));
        expect(panel.isDirty()).toBe(false);
        expect(panel.onSaveSilently()!.data.test_payload).toEqual({});
    });

    it('shows and keeps a saved payload instead of the sample', () => {
        open(telegramNode({ message: { message_id: 9 } }));

        expect(editor().testPayload.text()).toBe(formatTestPayload({ message: { message_id: 9 } }));
        expect(panel.onSaveSilently()!.data.test_payload).toEqual({ message: { message_id: 9 } });
    });

    it('saves an edited seed', () => {
        open(telegramNode());

        editor().onTestPayloadTextChange('{"message": {"message_id": 5}}');

        expect(panel.onSaveSilently()!.data.test_payload).toEqual({ message: { message_id: 5 } });
    });

    it('re-seeds an unedited sample when the picked fields change', () => {
        open(telegramNode());
        dialogResult = [MESSAGE_ID, MESSAGE_TEXT];

        panel.onEditing();

        expect(editor().testPayload.text()).toBe(sampleText([MESSAGE_ID, MESSAGE_TEXT]));
        expect(editor().testPayload.isEdited()).toBe(false);
    });

    it('keeps an edited payload when the picked fields change', () => {
        open(telegramNode());
        editor().onTestPayloadTextChange('{"message": {}}');
        dialogResult = [MESSAGE_ID, MESSAGE_TEXT];

        panel.onEditing();

        expect(editor().testPayload.text()).toBe('{"message": {}}');
    });

    it('stays dirty with an invalid edit, keeps the saved payload and says it was not saved', () => {
        open(telegramNode({ message: { message_id: 9 } }));
        editor().onTestPayloadTextChange('{"message": ');
        expect(panel.isDirty()).toBe(true);

        expect(panel.onSave()!.data.test_payload).toEqual({ message: { message_id: 9 } });
        expect(toast['warning']).toHaveBeenCalledWith(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
    });

    it('says an invalid payload edit was not saved on Ctrl+S as well', () => {
        open(telegramNode({ message: { message_id: 9 } }));
        panel.form.patchValue({ node_name: 'Renamed' });
        editor().onTestPayloadTextChange('{"message": ');

        const savedNode = panel.onSaveSilently();

        expect(savedNode!.node_name).toBe('Renamed');
        expect(savedNode!.data.test_payload).toEqual({ message: { message_id: 9 } });
        expect(toast['warning']).toHaveBeenCalledTimes(1);
        expect(toast['warning']).toHaveBeenCalledWith(INVALID_TEST_PAYLOAD_NOT_SAVED_MESSAGE);
        expect(panel.isDirty()).toBe(true);
    });

    it('warns about nothing when a valid payload edit is saved', () => {
        open(telegramNode());
        editor().onTestPayloadTextChange('{"message": {"message_id": 5}}');

        panel.onSaveSilently();
        panel.onSave();

        expect(toast['warning']).not.toHaveBeenCalled();
    });

    describe('while the form is invalid (no bot key)', () => {
        const SAVED_PAYLOAD = { message: { message_id: 9 } };
        const EDITED_PAYLOAD = { message: { message_id: 5 } };

        function openWithoutBotKey(): void {
            const node = telegramNode(SAVED_PAYLOAD);
            open({ ...node, data: { ...node.data, telegram_bot_api_key_secret_id: null } });
            expect(panel.form.invalid).toBe(true);
        }

        it('onSave (close, Esc, autosave) saves a valid payload edit alone onto the last saved node', () => {
            openWithoutBotKey();
            const lastSavedNode = panel.node();
            panel.form.patchValue({ node_name: 'Renamed' });
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            const savedNode = panel.onSave();

            expect(savedNode).toEqual({
                ...lastSavedNode,
                data: { ...lastSavedNode.data, test_payload: EDITED_PAYLOAD },
            });
            expect(toast['warning']).toHaveBeenCalledTimes(1);
            expect(toast['warning']).toHaveBeenCalledWith(TEST_PAYLOAD_SAVED_OTHER_CHANGES_NOT_SAVED_MESSAGE);
            // The rename is still unsaved; the payload is not saved again.
            expect(panel.isDirty()).toBe(true);
            expect(panel.onSave()).toBeNull();
            expect(toast['warning']).toHaveBeenCalledTimes(1);
        });

        it('onSaveSilently (Ctrl+S) saves nothing and leaves every edit as it was', () => {
            openWithoutBotKey();
            panel.form.patchValue({ node_name: 'Renamed' });
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));

            expect(panel.onSaveSilently()).toBeNull();

            expect(toast['warning']).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(true);
            expect(panel.form.value.node_name).toBe('Renamed');
            expect(editor().testPayload.text()).toBe(JSON.stringify(EDITED_PAYLOAD));
            expect(editor().testPayload.isEdited()).toBe(true);
            // The payload edit is still unsaved: closing the panel saves it.
            expect(panel.onSave()!.data.test_payload).toEqual(EDITED_PAYLOAD);
        });

        it('is clean after saving the payload when it was the only edit', () => {
            openWithoutBotKey();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));
            expect(panel.isDirty()).toBe(true);

            expect(panel.onSave()!.data.test_payload).toEqual(EDITED_PAYLOAD);

            expect(toast['warning']).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(false);
            expect(editor().testPayload.text()).toBe(JSON.stringify(EDITED_PAYLOAD));
        });

        it('saves a payload edit that breaks a field rule, as a full save does', () => {
            openWithoutBotKey();
            editor().onTestPayloadTextChange('{"callback_query": {}}');
            expect(editor().testPayload.check().ruleErrors).not.toEqual([]);

            expect(panel.onSave()!.data.test_payload).toEqual({ callback_query: {} });
        });

        it('saves nothing for payload text that is not valid JSON', () => {
            openWithoutBotKey();
            editor().onTestPayloadTextChange('{"message": ');

            expect(panel.onSave()).toBeNull();
            expect(panel.onSaveSilently()).toBeNull();
            expect(toast['warning']).not.toHaveBeenCalled();
            expect(panel.isDirty()).toBe(true);
        });

        it('saves nothing when the payload was not edited', () => {
            openWithoutBotKey();
            panel.form.patchValue({ node_name: 'Renamed' });

            expect(panel.onSave()).toBeNull();
            expect(panel.onSaveSilently()).toBeNull();
            expect(toast['warning']).not.toHaveBeenCalled();
        });

        it('saves nothing for an unedited sample', () => {
            const node = telegramNode();
            open({ ...node, data: { ...node.data, telegram_bot_api_key_secret_id: null } });

            expect(panel.onSave()).toBeNull();
        });

        it('saves the whole node once the bot key is picked', () => {
            openWithoutBotKey();
            editor().onTestPayloadTextChange(JSON.stringify(EDITED_PAYLOAD));
            panel.onSave();

            panel.form.patchValue({ telegram_bot_api_key_secret_id: 7 });
            const savedNode = panel.onSave();

            expect(savedNode!.data.telegram_bot_api_key_secret_id).toBe(7);
            expect(savedNode!.data.test_payload).toEqual(EDITED_PAYLOAD);
            expect(panel.isDirty()).toBe(false);
        });
    });

    it('reports payload keys that are not picked fields while editable', () => {
        open(telegramNode({ callback_query: {} }));

        expect(editor().testPayload.check().ruleErrors).toEqual([
            "'callback_query': not a field parent selected on this node",
        ]);
    });

    it('blocks the run with a hint, not an error, while no fields are picked', () => {
        open(telegramNode());
        dialogResult = [];

        panel.onEditing();

        expect(editor().testPayload.check().hints).toEqual([TELEGRAM_NO_FIELDS_SELECTED_MESSAGE]);
        expect(editor().testPayload.check().ruleErrors).toEqual([]);
        expect(editor().testPayload.runBlocker()).toBe(TELEGRAM_NO_FIELDS_SELECTED_MESSAGE);
    });

    it('shows no field rule errors in read-only mode, only JSON errors', () => {
        canUpdateFlows = false;
        open(telegramNode({ callback_query: {} }));

        expect(editor().testPayload.check().ruleErrors).toEqual([]);

        editor().testPayload.reset('{"message": ');
        expect(editor().testPayload.check().parseError).not.toBeNull();
    });

    describe('Insert example', () => {
        it('nests the picked fields under their parent, as the runtime update is', () => {
            open(telegramNode({ message: { message_id: 9 } }));
            confirmResult = true;

            editor().insertExamplePayload();

            expect(editor().testPayload.text()).toBe('{\n  "message": {\n    "message_id": 1\n  }\n}');
            expect(JSON.parse(editor().testPayload.text())).toEqual({ message: { message_id: 1 } });
        });

        it('replaces an unedited seed without asking and counts it as an edit that is saved', () => {
            open(telegramNode());

            editor().insertExamplePayload();

            expect(confirm).not.toHaveBeenCalled();
            expect(editor().testPayload.isEdited()).toBe(true);
            expect(panel.isDirty()).toBe(true);
            expect(panel.onSaveSilently()!.data.test_payload).toEqual({ message: { message_id: 1 } });
        });

        it('replaces an empty payload without asking', () => {
            open(telegramNode());
            editor().onTestPayloadTextChange('{}');

            editor().insertExamplePayload();

            expect(confirm).not.toHaveBeenCalled();
            expect(editor().testPayload.text()).toBe(sampleText([MESSAGE_ID]));
        });

        it('asks before replacing a payload the user edited and replaces it on yes', () => {
            open(telegramNode());
            editor().onTestPayloadTextChange('{"message": {"message_id": 5}}');
            confirmResult = true;

            editor().insertExamplePayload();

            expect(confirm).toHaveBeenCalledTimes(1);
            expect(editor().testPayload.text()).toBe(sampleText([MESSAGE_ID]));
        });

        it('keeps the user payload when the replacement is declined or the dialog is closed', () => {
            open(telegramNode());
            editor().onTestPayloadTextChange('{"message": ');

            confirmResult = false;
            editor().insertExamplePayload();
            confirmResult = 'close';
            editor().insertExamplePayload();

            expect(confirm).toHaveBeenCalledTimes(2);
            expect(editor().testPayload.text()).toBe('{"message": ');
        });

        it('asks before replacing a previously saved payload as well', () => {
            open(telegramNode({ message: { message_id: 9 } }));
            confirmResult = false;

            editor().insertExamplePayload();

            expect(confirm).toHaveBeenCalledTimes(1);
            expect(editor().testPayload.text()).toBe(formatTestPayload({ message: { message_id: 9 } }));
        });

        it('drops the server errors of the previous run', () => {
            open(telegramNode());
            const testRun = TestBed.inject(FlowTestRunService);
            testRun.setServerErrors(panel.node().id, ["'message.text': field not selected on this node"]);

            editor().insertExamplePayload();

            expect(editor().testPayload.serverErrors()).toEqual([]);
        });

        it('is disabled with a reason while no fields are picked', () => {
            open(telegramNode());
            expect(editor().insertExampleDisabledReason()).toBeNull();
            dialogResult = [];
            panel.onEditing();
            editor().onTestPayloadTextChange('{"x": 1}');

            editor().insertExamplePayload();

            expect(editor().insertExampleDisabledReason()).toBe(INSERT_EXAMPLE_NO_FIELDS_REASON);
            expect(editor().testPayload.text()).toBe('{"x": 1}');
            expect(confirm).not.toHaveBeenCalled();
        });

        it('does nothing in read-only mode', () => {
            canUpdateFlows = false;
            open(telegramNode({ message: { message_id: 9 } }));

            editor().insertExamplePayload();

            expect(confirm).not.toHaveBeenCalled();
            expect(editor().testPayload.isEdited()).toBe(false);
        });
    });
});

describe('TelegramTriggerNodePanelComponent field models info', () => {
    let fixture: ComponentFixture<TelegramTriggerNodePanelComponent>;
    let canUpdateFlows: boolean;

    beforeEach(() => {
        canUpdateFlows = true;
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } },
                {
                    provide: PermissionsService,
                    useValue: { can: () => canUpdateFlows, canAny: () => canUpdateFlows },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { secrets: signal([]), maskTail: () => '', getSecrets: () => of([]) },
                },
                { provide: Dialog, useValue: { open: () => ({ closed: of(undefined) }) } },
            ],
        });
        // Only the panel's own markup is under test: child controls (and Monaco) stay unrendered elements.
        TestBed.overrideComponent(TelegramTriggerNodePanelComponent, {
            set: { imports: [], schemas: [NO_ERRORS_SCHEMA] },
        });
    });

    function open(isExpanded: boolean): HTMLElement {
        fixture = TestBed.createComponent(TelegramTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', telegramNode());
        fixture.componentRef.setInput('isExpanded', isExpanded);
        fixture.detectChanges();
        return fixture.nativeElement;
    }

    function outputFieldsLayout(root: HTMLElement): string[] {
        const section = root.querySelector('.output-fields-section')!;
        return Array.from(section.children).map((child) => child.classList[0]);
    }

    it.each([
        ['compact', false],
        ['expanded', true],
    ])('shows the info under the picked fields and Editing button, not in the payload column (%s)', (_, isExpanded) => {
        const root = open(isExpanded);

        expect(outputFieldsLayout(root)).toEqual([
            'output-fields__label',
            'output-fields__container',
            'output-fields__info',
        ]);
        const link = root.querySelector<HTMLAnchorElement>('.output-fields__info-link')!;
        expect(link.href).toBe('https://core.telegram.org/bots/api#available-types');
        expect(link.target).toBe('_blank');
        expect(root.querySelector('.code-editor-section .output-fields__info')).toBeNull();
    });

    it.each([
        ['compact', false],
        ['expanded', true],
    ])('gives the payload section the Insert example action (%s)', (_, isExpanded) => {
        open(isExpanded);

        const section = fixture.debugElement.query(By.css('app-test-payload-section'));
        expect(section.properties['actionIcon']).toBe(INSERT_EXAMPLE_PAYLOAD_ICON);
        expect(section.properties['actionLabel']).toBe(INSERT_EXAMPLE_PAYLOAD_LABEL);
        expect(section.properties['actionDisabledReason']).toBeNull();
        expect(section.properties['readOnly']).toBe(false);
    });

    describe('Insert example icon in the payload editor header', () => {
        beforeEach(() => {
            // The real payload section, so the panel -> section -> editor header wiring is under test;
            // the JSON editor (Monaco) stays an unrendered element.
            TestBed.overrideComponent(TelegramTriggerNodePanelComponent, {
                set: { imports: [TestPayloadSectionComponent], schemas: [NO_ERRORS_SCHEMA] },
            });
            TestBed.overrideComponent(TestPayloadSectionComponent, {
                remove: { imports: [JsonEditorComponent] },
                add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
            });
        });

        function jsonEditor() {
            return fixture.debugElement.query(By.css('app-test-payload-section app-json-editor'));
        }

        it.each([
            ['compact', false],
            ['expanded', true],
        ])('is bound to the editor header (%s)', (_, isExpanded) => {
            open(isExpanded);

            expect(jsonEditor().properties['actionIcon']).toBe(INSERT_EXAMPLE_PAYLOAD_ICON);
            expect(jsonEditor().properties['actionLabel']).toBe(INSERT_EXAMPLE_PAYLOAD_LABEL);
            expect(jsonEditor().properties['actionDisabledReason']).toBeNull();
        });

        it.each([
            ['compact', false],
            ['expanded', true],
        ])('is not given to a viewer (%s)', (_, isExpanded) => {
            canUpdateFlows = false;

            open(isExpanded);

            expect(jsonEditor().properties['actionIcon']).toBeNull();
        });
    });

    it('marks the payload section read-only for a viewer, which hides the action', () => {
        canUpdateFlows = false;

        open(false);

        // On an unrendered element Angular records the `readonly` binding under its DOM name, `readOnly`.
        expect(fixture.debugElement.query(By.css('app-test-payload-section')).properties['readOnly']).toBe(true);
    });

    it('shows the info to a viewer as well', () => {
        canUpdateFlows = false;

        const root = open(false);

        expect(root.querySelector('.output-fields__info')).not.toBeNull();
    });
});
