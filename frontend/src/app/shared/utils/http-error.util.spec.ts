import { HttpErrorResponse } from '@angular/common/http';

import { extractHttpErrorMessage } from './http-error.util';

function badRequest(errors: Record<string, unknown>): HttpErrorResponse {
    return new HttpErrorResponse({ status: 400, error: { errors } });
}

describe('extractHttpErrorMessage for bulk-save node uuid errors', () => {
    it('reads a per-node uuid error', () => {
        const error = badRequest({
            python_node_list: [
                { index: 0, errors: { uuid: ['This uuid is already used by another node of this flow.'] } },
            ],
            task_node_list: [
                { index: 1, errors: { uuid: ['This uuid is used by more than one node in the request.'] } },
            ],
        });

        expect(extractHttpErrorMessage(error)).toBe(
            'uuid: This uuid is already used by another node of this flow.; ' +
                'uuid: This uuid is used by more than one node in the request.'
        );
    });

    it('reads a per-node error for a node that targets another flow', () => {
        const error = badRequest({ python_node_list: [{ index: 0, errors: { graph: ['Must be this flow.'] } }] });

        expect(extractHttpErrorMessage(error)).toBe('graph: Must be this flow.');
    });

    it('reads the top-level uuid conflict the backend reports when a save races another one', () => {
        const error = badRequest({ nodes: ['This uuid is already used by another node of this flow.'] });

        expect(extractHttpErrorMessage(error)).toBe('nodes: This uuid is already used by another node of this flow.');
    });
});
