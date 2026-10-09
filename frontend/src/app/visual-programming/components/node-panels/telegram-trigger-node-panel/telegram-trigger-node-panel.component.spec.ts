import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import {
    Component,
    CUSTOM_ELEMENTS_SCHEMA,
    input,
    NO_ERRORS_SCHEMA,
    Signal,
    signal,
    WritableSignal,
} from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ConfirmationDialogService, ConfirmationResult, JsonEditorComponent } from '@shared/components';
import { NodeType } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { of } from 'rxjs';

import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { GetTelegramTriggerNodeRequest, TelegramTriggerNodeField } from '../../../core/models/telegram-trigger.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { FlowTestRunService } from '../../../services/flow-test-run.service';
import { SavedFlowStateService } from '../../../services/saved-flow-state.service';
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

function registrationNode(
    overrides: Partial<TelegramTriggerNodeModel['data']> = {},
    nodeOverrides: Partial<TelegramTriggerNodeModel> = {}
): TelegramTriggerNodeModel {
    return {
        id: 'telegram-1',
        backendId: 12,
        type: NodeType.TELEGRAM_TRIGGER,
        node_name: 'Telegram Trigger #1',
        data: {
            telegram_bot_api_key_secret_id: 5,
            webhook_trigger: 3,
            fields: [],
            test_payload: {},
            ...overrides,
        },
        position: { x: 0, y: 0 },
        ports: null,
        color: '',
        icon: '',
        size: { width: 200, height: 100 },
        input_map: {},
        output_variable_path: null,
        ...nodeOverrides,
    };
}

// The Telegram registration check itself (fetching, rendering, backendId null never calling the
// API) is covered in telegram-webhook-registration.component.spec.ts; this panel only decides
// which saved values the check reads and whether the form has connection edits it cannot reflect.
interface Panel {
    panel: TelegramTriggerNodePanelComponent;
    hasUnsavedConnectionChanges: Signal<boolean>;
    savedBackendId: Signal<number | null>;
    savedBotKeySecretId: Signal<number | null>;
    destroy: () => void;
}

function configure({ isPreview = false }: { isPreview?: boolean } = {}): void {
    TestBed.configureTestingModule({
        providers: [
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: FlowsApiService, useValue: { getTelegramTriggerWebhookInfo: vi.fn() } },
            {
                provide: SecretsStorageService,
                useValue: { getSecrets: () => of([]), secrets: () => [], maskTail: (tail: string) => tail },
            },
        ],
    });
    TestBed.overrideComponent(TelegramTriggerNodePanelComponent, { set: { template: '', imports: [] } });
}

function markSaved(...nodes: TelegramTriggerNodeModel[]): void {
    TestBed.inject(SavedFlowStateService).setSavedFlow({ nodes, connections: [] });
}

function open(node: TelegramTriggerNodeModel): Panel {
    const fixture = TestBed.createComponent(TelegramTriggerNodePanelComponent);
    fixture.componentRef.setInput('node', node);
    fixture.detectChanges();
    const panel = fixture.componentInstance;
    return {
        panel,
        hasUnsavedConnectionChanges: panel['hasUnsavedConnectionChanges'],
        savedBackendId: panel['savedBackendId'],
        savedBotKeySecretId: panel['savedBotKeySecretId'],
        destroy: () => fixture.destroy(),
    };
}

/** Opens a node whose canvas state equals its saved state, as right after loading the flow. */
function openSaved(node: TelegramTriggerNodeModel): Panel {
    configure();
    markSaved(node);
    return open(node);
}

describe('TelegramTriggerNodePanelComponent', () => {
    it('reports no unsaved connection changes for a freshly opened node', () => {
        const { hasUnsavedConnectionChanges } = openSaved(registrationNode());

        expect(hasUnsavedConnectionChanges()).toBe(false);
    });

    it('treats a loaded nested webhook trigger object and its id as the same trigger', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(
            registrationNode({ webhook_trigger: { id: 3, path: 'bot', provider_type: 'ngrok' } as never })
        );

        panel.form.get('webhook_trigger')!.setValue(3);

        expect(hasUnsavedConnectionChanges()).toBe(false);
    });

    it('flags a bot key that differs from the saved node', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(registrationNode());

        panel.form.get('telegram_bot_api_key_secret_id')!.setValue(6);

        expect(hasUnsavedConnectionChanges()).toBe(true);
    });

    it('flags a webhook trigger that differs from the saved node', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(registrationNode());

        panel.form.get('webhook_trigger')!.setValue(4);

        expect(hasUnsavedConnectionChanges()).toBe(true);
    });

    it('does not flag edits to fields unrelated to the Telegram registration', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(registrationNode());

        panel.form.get('node_name')!.setValue('Renamed trigger');

        expect(hasUnsavedConnectionChanges()).toBe(false);
    });

    it('passes the saved backendId and bot key to the registration check', () => {
        const { savedBackendId, savedBotKeySecretId } = openSaved(registrationNode());

        expect(savedBackendId()).toBe(12);
        expect(savedBotKeySecretId()).toBe(5);
    });

    it('treats a never-saved node as having nothing saved to check or compare against', () => {
        configure();
        const { panel, hasUnsavedConnectionChanges, savedBackendId, savedBotKeySecretId } = open(
            registrationNode({}, { backendId: null })
        );

        panel.form.get('telegram_bot_api_key_secret_id')!.setValue(6);

        expect(hasUnsavedConnectionChanges()).toBe(false);
        expect(savedBackendId()).toBeNull();
        expect(savedBotKeySecretId()).toBeNull();
    });

    // Switching panels autosaves the form into the canvas node without calling the backend, so
    // node() carries the new key while the backend (and Telegram) still has the old one.
    it('keeps the saved bot key and the unsaved note after an autosave on panel switch and reopening', () => {
        const savedNode = registrationNode({ telegram_bot_api_key_secret_id: 5 });
        const first = openSaved(savedNode);
        first.panel.form.get('telegram_bot_api_key_secret_id')!.setValue(6);
        // What the panel-switch autosave writes into the canvas node.
        const autosavedNode = first.panel['createUpdatedNode']();
        first.destroy();

        const reopened = open(autosavedNode);

        expect(reopened.panel.form.get('telegram_bot_api_key_secret_id')!.value).toBe(6);
        expect(reopened.hasUnsavedConnectionChanges()).toBe(true);
        expect(reopened.savedBotKeySecretId()).toBe(5);
    });

    it('clears the unsaved note once the new bot key is saved', () => {
        const first = openSaved(registrationNode({ telegram_bot_api_key_secret_id: 5 }));
        first.panel.form.get('telegram_bot_api_key_secret_id')!.setValue(6);
        const updatedNode = first.panel['createUpdatedNode']();

        markSaved(updatedNode);

        expect(first.hasUnsavedConnectionChanges()).toBe(false);
        expect(first.savedBotKeySecretId()).toBe(6);
    });

    it('shows the registration check in the live editor', () => {
        const { panel } = openSaved(registrationNode());

        expect(panel['showsWebhookRegistration']).toBe(true);
    });

    // The preview's own SavedFlowStateService is never written, so the check would always claim
    // the node is unsaved; the live registration says nothing about an old version anyway.
    it('hides the registration check in a version preview', () => {
        configure({ isPreview: true });
        const { panel } = open(registrationNode({}, { backendId: null }));

        expect(panel['showsWebhookRegistration']).toBe(false);
    });
});

/** Stands in for the registration check so the real panel template can be rendered cheaply. */
@Component({ selector: 'app-telegram-webhook-registration', template: '' })
class TelegramWebhookRegistrationStubComponent {
    readonly nodeId = input<string>();
    readonly backendId = input<number | null>(null);
    readonly botKeySecretId = input<number | null>(null);
    readonly hasUnsavedConnectionChanges = input<boolean>(false);
    readonly readonly = input<boolean>(false);
}

describe('TelegramTriggerNodePanelComponent template', () => {
    // Real panel template; every other child is left unrendered by NO_ERRORS_SCHEMA.
    function renderWithReadOnly(
        isReadOnly: WritableSignal<boolean>
    ): ComponentFixture<TelegramTriggerNodePanelComponent> {
        TestBed.configureTestingModule({
            providers: [
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                {
                    provide: FlowReadOnlyService,
                    useValue: { isPreview: false, isReadOnly, notifyBlocked: vi.fn() },
                },
                {
                    provide: SecretsStorageService,
                    useValue: { getSecrets: () => of([]), secrets: () => [], maskTail: (tail: string) => tail },
                },
            ],
        });
        TestBed.overrideComponent(TelegramTriggerNodePanelComponent, {
            set: { imports: [TelegramWebhookRegistrationStubComponent], schemas: [NO_ERRORS_SCHEMA] },
        });
        const node = registrationNode();
        TestBed.inject(SavedFlowStateService).setSavedFlow({ nodes: [node], connections: [] });
        const fixture = TestBed.createComponent(TelegramTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
        return fixture;
    }

    function registrationReadonly(fixture: ComponentFixture<TelegramTriggerNodePanelComponent>): boolean | undefined {
        return fixture.debugElement
            .query(By.directive(TelegramWebhookRegistrationStubComponent))
            ?.injector.get(TelegramWebhookRegistrationStubComponent)
            .readonly();
    }

    it('passes FlowReadOnlyService.isReadOnly() to the registration check as readonly', () => {
        const isReadOnly = signal(false);
        const fixture = renderWithReadOnly(isReadOnly);
        expect(registrationReadonly(fixture)).toBe(false);

        isReadOnly.set(true);
        fixture.detectChanges();

        expect(registrationReadonly(fixture)).toBe(true);
        fixture.destroy();
    });

    it('starts read-only when the user cannot change the flow', () => {
        const fixture = renderWithReadOnly(signal(true));

        expect(registrationReadonly(fixture)).toBe(true);
        fixture.destroy();
    });
});

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
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
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
