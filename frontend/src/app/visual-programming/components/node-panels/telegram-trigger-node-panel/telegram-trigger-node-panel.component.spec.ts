import { Signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';
import { SecretsStorageService } from '@shared/services';
import { of } from 'rxjs';

import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { TelegramTriggerNodeModel } from '../../../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../../../core/providers/flow-editor-preview.token';
import { SavedFlowStateService } from '../../../services/saved-flow-state.service';
import { TelegramTriggerNodePanelComponent } from './telegram-trigger-node-panel.component';

function telegramNode(
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
        const { hasUnsavedConnectionChanges } = openSaved(telegramNode());

        expect(hasUnsavedConnectionChanges()).toBe(false);
    });

    it('treats a loaded nested webhook trigger object and its id as the same trigger', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(
            telegramNode({ webhook_trigger: { id: 3, path: 'bot', provider_type: 'ngrok' } as never })
        );

        panel.form.get('webhook_trigger')!.setValue(3);

        expect(hasUnsavedConnectionChanges()).toBe(false);
    });

    it('flags a bot key that differs from the saved node', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(telegramNode());

        panel.form.get('telegram_bot_api_key_secret_id')!.setValue(6);

        expect(hasUnsavedConnectionChanges()).toBe(true);
    });

    it('flags a webhook trigger that differs from the saved node', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(telegramNode());

        panel.form.get('webhook_trigger')!.setValue(4);

        expect(hasUnsavedConnectionChanges()).toBe(true);
    });

    it('does not flag edits to fields unrelated to the Telegram registration', () => {
        const { panel, hasUnsavedConnectionChanges } = openSaved(telegramNode());

        panel.form.get('node_name')!.setValue('Renamed trigger');

        expect(hasUnsavedConnectionChanges()).toBe(false);
    });

    it('passes the saved backendId and bot key to the registration check', () => {
        const { savedBackendId, savedBotKeySecretId } = openSaved(telegramNode());

        expect(savedBackendId()).toBe(12);
        expect(savedBotKeySecretId()).toBe(5);
    });

    it('treats a never-saved node as having nothing saved to check or compare against', () => {
        configure();
        const { panel, hasUnsavedConnectionChanges, savedBackendId, savedBotKeySecretId } = open(
            telegramNode({}, { backendId: null })
        );

        panel.form.get('telegram_bot_api_key_secret_id')!.setValue(6);

        expect(hasUnsavedConnectionChanges()).toBe(false);
        expect(savedBackendId()).toBeNull();
        expect(savedBotKeySecretId()).toBeNull();
    });

    // Switching panels autosaves the form into the canvas node without calling the backend, so
    // node() carries the new key while the backend (and Telegram) still has the old one.
    it('keeps the saved bot key and the unsaved note after an autosave on panel switch and reopening', () => {
        const savedNode = telegramNode({ telegram_bot_api_key_secret_id: 5 });
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
        const first = openSaved(telegramNode({ telegram_bot_api_key_secret_id: 5 }));
        first.panel.form.get('telegram_bot_api_key_secret_id')!.setValue(6);
        const updatedNode = first.panel['createUpdatedNode']();

        markSaved(updatedNode);

        expect(first.hasUnsavedConnectionChanges()).toBe(false);
        expect(first.savedBotKeySecretId()).toBe(6);
    });

    it('shows the registration check in the live editor', () => {
        const { panel } = openSaved(telegramNode());

        expect(panel['showsWebhookRegistration']).toBe(true);
    });

    // The preview's own SavedFlowStateService is never written, so the check would always claim
    // the node is unsaved; the live registration says nothing about an old version anyway.
    it('hides the registration check in a version preview', () => {
        configure({ isPreview: true });
        const { panel } = open(telegramNode({}, { backendId: null }));

        expect(panel['showsWebhookRegistration']).toBe(false);
    });
});
