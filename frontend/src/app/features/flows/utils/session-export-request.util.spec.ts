import { sessionExportRequest, SessionListExportFilters } from './session-export-request.util';

describe('sessionExportRequest', () => {
    it.each<[string, ReadonlySet<number>, SessionListExportFilters, object]>([
        [
            'the selected sessions, whatever the filters',
            new Set([4, 2]),
            { graphId: 7, statuses: ['error'], errorCauseOnly: true, idSearch: '12' },
            { ids: [4, 2], export_format: 'csv' },
        ],
        [
            'every session the filters match when none is selected',
            new Set(),
            { graphId: 7, statuses: ['error', 'end'], errorCauseOnly: true, idSearch: '12' },
            { graph_id: 7, status: ['error', 'end'], is_error_cause: true, id_search: '12', export_format: 'csv' },
        ],
        [
            'every session when no filter narrows the list',
            new Set(),
            { graphId: null, statuses: [], errorCauseOnly: false, idSearch: '' },
            { export_format: 'csv' },
        ],
        ['every session when no filter is given', new Set(), {}, { export_format: 'csv' }],
        ['the sessions of flow 0, a real id', new Set(), { graphId: 0 }, { graph_id: 0, export_format: 'csv' }],
    ])('exports %s', (_case, selected, filters, expected) => {
        expect(sessionExportRequest(selected, filters, 'csv')).toEqual(expected);
    });
});
