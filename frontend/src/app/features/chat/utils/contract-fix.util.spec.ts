import { GraphDto } from '../../flows/models/graph.model';
import { ChatContractMissing } from '../models/chat.model';
import { contractFixPayload, hasContractGaps, isAutoFixable } from './contract-fix.util';

const NOTHING_MISSING: ChatContractMissing = {
    missing_start_node: false,
    missing_end_node: false,
    start_variables: [],
    end_outputs: [],
};

const FULL_DOMAIN_VARIABLES = {
    chat_history: [],
    user_message: '',
    action: null,
    chat_extra_data: {},
    chat_user_id: null,
    chat_conversation_id: '',
    reply: '',
    actions: [],
    request_human: false,
};

const FULL_OUTPUT_MAP = {
    reply: 'variables.reply',
    actions: 'variables.actions',
    request_human: 'variables.request_human',
};

function graph(startVariables: Record<string, unknown>, outputMap: Record<string, unknown>): GraphDto {
    return {
        id: 7,
        save_version: 3,
        start_node_list: [{ id: 11, graph: 7, variables: startVariables, metadata: { position: { x: 1, y: 2 } } }],
        end_node_list: [{ id: 12, graph: 7, output_map: outputMap, metadata: { position: { x: 9, y: 2 } } }],
    } as unknown as GraphDto;
}

describe('contractFixPayload', () => {
    it('adds every missing chat variable and output to a flow that has none', () => {
        expect(contractFixPayload(graph({}, {}))).toEqual({
            save_version: 3,
            start_node_list: [
                {
                    id: 11,
                    graph: 7,
                    variables: { variables: FULL_DOMAIN_VARIABLES },
                    metadata: { position: { x: 1, y: 2 } },
                },
            ],
            end_node_list: [{ id: 12, graph: 7, output_map: FULL_OUTPUT_MAP, metadata: { position: { x: 9, y: 2 } } }],
        });
    });

    it('keeps existing values, other Domain keys and persistent variables, adding only what is missing', () => {
        const payload = contractFixPayload(
            graph(
                {
                    variables: { context: 'ctx', user_message: 'hi', reply: 'Hello' },
                    persistent_variables: { user: ['context'], organization: [] },
                },
                { context: 'variables.context', reply: 'variables.answer' }
            )
        );

        expect(payload?.start_node_list[0]['variables']).toEqual({
            variables: { ...FULL_DOMAIN_VARIABLES, context: 'ctx', user_message: 'hi', reply: 'Hello' },
            persistent_variables: { user: ['context'], organization: [] },
        });
        expect(payload?.end_node_list[0]['output_map']).toEqual({
            context: 'variables.context',
            reply: 'variables.answer',
            actions: 'variables.actions',
            request_human: 'variables.request_human',
        });
    });

    it('adds to a flat Domain beside its own keys, since the backend reads a Domain without `variables` whole', () => {
        const payload = contractFixPayload(graph({ context: 'ctx', user_message: 'hi' }, FULL_OUTPUT_MAP));

        expect(payload?.start_node_list[0]['variables']).toEqual({
            ...FULL_DOMAIN_VARIABLES,
            context: 'ctx',
            user_message: 'hi',
        });
    });

    it('sends only the node that lacks something', () => {
        const payload = contractFixPayload(graph({ variables: FULL_DOMAIN_VARIABLES }, { reply: 'variables.reply' }));

        expect(payload?.start_node_list).toEqual([]);
        expect(payload?.end_node_list.map((node) => node['id'])).toEqual([12]);
    });

    it('is null when the flow has every chat variable and output', () => {
        expect(contractFixPayload(graph({ variables: FULL_DOMAIN_VARIABLES }, FULL_OUTPUT_MAP))).toBeNull();
    });

    it('is null when the flow has no start or end node to add to', () => {
        const empty = { ...graph({}, {}), start_node_list: [], end_node_list: [] } as GraphDto;

        expect(contractFixPayload(empty)).toBeNull();
    });
});

describe('hasContractGaps and isAutoFixable', () => {
    it.each([
        ['nothing missing', NOTHING_MISSING, false, true],
        ['start variables missing', { ...NOTHING_MISSING, start_variables: ['user_message'] }, true, true],
        ['reply missing', { ...NOTHING_MISSING, end_outputs: ['reply'] }, true, true],
        ['a variable the fix does not add', { ...NOTHING_MISSING, start_variables: ['locale'] }, true, false],
        ['an output the fix does not add', { ...NOTHING_MISSING, end_outputs: ['summary'] }, true, false],
        ['no start node', { ...NOTHING_MISSING, missing_start_node: true }, true, false],
        ['no end node', { ...NOTHING_MISSING, missing_end_node: true }, true, false],
    ])('%s', (_case, missing, gaps, fixable) => {
        expect(hasContractGaps(missing)).toBe(gaps);
        expect(isAutoFixable(missing)).toBe(fixable);
    });
});
