import { TELEGRAM_TRIGGER_FIELDS } from '../../core/constants/telegram-trigger-fields';
import {
    buildTelegramSamplePayload,
    TELEGRAM_NO_FIELDS_SELECTED_MESSAGE,
    TelegramPickedField,
    validateTelegramTestPayload,
} from './telegram-test-payload.validator';

const picked: TelegramPickedField[] = [
    { parent: 'message', field_name: 'text' },
    { parent: 'message', field_name: 'chat' },
    { parent: 'callback_query', field_name: 'data' },
];

describe('validateTelegramTestPayload', () => {
    const noFieldsHint = { errors: [], hints: [TELEGRAM_NO_FIELDS_SELECTED_MESSAGE] };

    it('R0: reports a node with no picked fields alone, as a hint rather than an error', () => {
        expect(validateTelegramTestPayload({ anything: 1, other: [] }, [])).toEqual(noFieldsHint);
        expect(validateTelegramTestPayload({}, [])).toEqual(noFieldsHint);
    });

    it('R1: rejects a top-level key that is not a picked parent', () => {
        expect(validateTelegramTestPayload({ edited_message: {} }, picked)).toEqual({
            errors: ["'edited_message': not a field parent selected on this node"],
            hints: [],
        });
    });

    describe('update envelope (update_id)', () => {
        const valid = { errors: [], hints: [] };

        it('accepts update_id next to a picked field', () => {
            expect(validateTelegramTestPayload({ update_id: 1, message: { text: 'hi' } }, picked)).toEqual(valid);
        });

        it('accepts update_id alone, like {}', () => {
            expect(validateTelegramTestPayload({ update_id: 1 }, picked)).toEqual(valid);
        });

        it('never inspects the update_id value', () => {
            expect(validateTelegramTestPayload({ update_id: 'not-a-number' }, picked)).toEqual(valid);
            expect(validateTelegramTestPayload({ update_id: { nested: true } }, picked)).toEqual(valid);
        });

        it('still rejects any other unpicked top-level key, with only that error', () => {
            expect(validateTelegramTestPayload({ update_id: 1, edited_message: {} }, picked)).toEqual({
                errors: ["'edited_message': not a field parent selected on this node"],
                hints: [],
            });
        });

        it('does not change R0: no picked fields is still reported alone', () => {
            expect(validateTelegramTestPayload({ update_id: 1 }, [])).toEqual(noFieldsHint);
        });
    });

    it('R2: rejects a parent whose value is not an object', () => {
        expect(validateTelegramTestPayload({ message: 'hello', callback_query: [] }, picked).errors).toEqual([
            "'message' must be an object",
            "'callback_query' must be an object",
        ]);
    });

    it('R3: rejects a field that is not picked for its parent', () => {
        expect(validateTelegramTestPayload({ message: { text: 'hi', data: 'x' } }, picked).errors).toEqual([
            "'message.data': field not selected on this node",
        ]);
    });

    it('allows {}, empty parents, omitted fields and any values', () => {
        const valid = { errors: [], hints: [] };
        expect(validateTelegramTestPayload({}, picked)).toEqual(valid);
        expect(validateTelegramTestPayload({ message: {} }, picked)).toEqual(valid);
        expect(validateTelegramTestPayload({ message: { text: null, chat: [1, 'two'] } }, picked)).toEqual(valid);
    });

    it('reports every problem at once', () => {
        expect(
            validateTelegramTestPayload({ unknown: 1, message: { from: {} }, callback_query: 5 }, picked).errors
        ).toEqual([
            "'unknown': not a field parent selected on this node",
            "'message.from': field not selected on this node",
            "'callback_query' must be an object",
        ]);
    });
});

describe('buildTelegramSamplePayload', () => {
    it('nests the catalog example of every picked field under its parent', () => {
        const textModel = TELEGRAM_TRIGGER_FIELDS.message.find((field) => field.field_name === 'text')?.model;
        const chatModel = TELEGRAM_TRIGGER_FIELDS.message.find((field) => field.field_name === 'chat')?.model;
        const dataModel = TELEGRAM_TRIGGER_FIELDS.callback_query.find((field) => field.field_name === 'data')?.model;

        expect(buildTelegramSamplePayload(picked)).toEqual({
            message: { text: textModel, chat: chatModel },
            callback_query: { data: dataModel },
        });
    });

    it('builds a sample the validator accepts', () => {
        expect(validateTelegramTestPayload(buildTelegramSamplePayload(picked), picked)).toEqual({
            errors: [],
            hints: [],
        });
    });

    it('leaves out the update envelope', () => {
        expect(Object.keys(buildTelegramSamplePayload(picked))).not.toContain('update_id');
    });

    it('is empty with no picked fields', () => {
        expect(buildTelegramSamplePayload([])).toEqual({});
    });
});
