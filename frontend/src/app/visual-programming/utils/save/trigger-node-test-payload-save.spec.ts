import { FlowModel } from '../../core/models/flow.model';
import { TelegramTriggerNodeModel, WebhookTriggerNodeModel } from '../../core/models/node.model';
import { GetTelegramTriggerNodeRequest } from '../../core/models/telegram-trigger.model';
import { GetWebhookTriggerNodeRequest } from '../../core/models/webhook-trigger';
import { mapTelegramTriggerNodeToModel } from '../load/nodes/telegram-trigger-node.mapper';
import { mapWebhookTriggerNodeToModel } from '../load/nodes/webhook-trigger-node.mapper';
import { getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

const webhookDto: GetWebhookTriggerNodeRequest = {
    id: 21,
    graph: 1,
    node_name: 'Webhook Trigger #1',
    python_code: { id: 5, libraries: [], code: 'def main(trigger_payload): pass', entrypoint: 'main' },
    input_map: {},
    output_variable_path: null,
    webhook_trigger_path: '',
    metadata: {},
    webhook_trigger: 3,
    test_payload: { id: '104', text: 'hello' },
};

const telegramDto: GetTelegramTriggerNodeRequest = {
    id: 22,
    graph: 1,
    node_name: 'Telegram Trigger #1',
    telegram_bot_api_key_secret_id: 9,
    fields: [{ id: 1, parent: 'message', field_name: 'text', variable_path: 'variables.text' }],
    metadata: {},
    webhook_trigger: 4,
    test_payload: { message: { text: 'hello' } },
};

const emptyFlow = { nodes: [], connections: [] } as unknown as FlowModel;

function flowOf(...nodes: unknown[]): FlowModel {
    return { nodes, connections: [] } as unknown as FlowModel;
}

function buildPayload(previous: FlowModel, current: FlowModel): Record<string, unknown> {
    return buildBulkSavePayload(
        1,
        getNodeDiff(previous, current),
        { toCreate: [], toDelete: [], toUpdate: [] },
        current,
        new Map(),
        1
    );
}

describe('trigger node test_payload save/load', () => {
    it('maps test_payload from both trigger DTOs', () => {
        expect(mapWebhookTriggerNodeToModel(webhookDto).data.test_payload).toEqual({ id: '104', text: 'hello' });
        expect(mapTelegramTriggerNodeToModel(telegramDto).data.test_payload).toEqual({
            message: { text: 'hello' },
        });
    });

    it('defaults a missing test_payload to an empty object', () => {
        const legacyWebhook = { ...webhookDto, test_payload: undefined } as unknown as GetWebhookTriggerNodeRequest;
        const legacyTelegram = { ...telegramDto, test_payload: undefined } as unknown as GetTelegramTriggerNodeRequest;

        expect(mapWebhookTriggerNodeToModel(legacyWebhook).data.test_payload).toEqual({});
        expect(mapTelegramTriggerNodeToModel(legacyTelegram).data.test_payload).toEqual({});
    });

    it('marks a webhook node dirty when only its test_payload changes', () => {
        const before = mapWebhookTriggerNodeToModel(webhookDto);
        const after: WebhookTriggerNodeModel = { ...before, data: { ...before.data, test_payload: { id: '105' } } };

        const diff = getNodeDiff(flowOf(before), flowOf(after));

        expect(diff.webhookNodes.toUpdate.map((update) => update.current.backendId)).toEqual([21]);
    });

    it('marks a telegram node dirty when only its test_payload changes', () => {
        const before = mapTelegramTriggerNodeToModel(telegramDto);
        const after: TelegramTriggerNodeModel = {
            ...before,
            data: { ...before.data, test_payload: { message: { text: 'bye' } } },
        };

        const diff = getNodeDiff(flowOf(before), flowOf(after));

        expect(diff.telegramNodes.toUpdate.map((update) => update.current.backendId)).toEqual([22]);
    });

    it('does not mark an unchanged trigger node dirty', () => {
        const webhook = mapWebhookTriggerNodeToModel(webhookDto);
        const telegram = mapTelegramTriggerNodeToModel(telegramDto);

        const diff = getNodeDiff(flowOf(webhook, telegram), flowOf({ ...webhook }, { ...telegram }));

        expect(diff.webhookNodes.toUpdate).toEqual([]);
        expect(diff.telegramNodes.toUpdate).toEqual([]);
    });

    it('sends test_payload in both bulk-save node lists', () => {
        const webhook: WebhookTriggerNodeModel = { ...mapWebhookTriggerNodeToModel(webhookDto), backendId: null };
        const telegram: TelegramTriggerNodeModel = { ...mapTelegramTriggerNodeToModel(telegramDto), backendId: null };

        const payload = buildPayload(emptyFlow, flowOf(webhook, telegram));

        expect(payload['webhook_trigger_node_list']).toEqual([
            expect.objectContaining({ test_payload: { id: '104', text: 'hello' } }),
        ]);
        expect(payload['telegram_trigger_node_list']).toEqual([
            expect.objectContaining({ test_payload: { message: { text: 'hello' } } }),
        ]);
    });
});
