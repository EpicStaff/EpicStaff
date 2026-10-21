import { getAdminDeleteConfirmationData } from './api-key-confirmation.util';

describe('getAdminDeleteConfirmationData', () => {
    it('names no one when the owner is hidden', () => {
        const message = getAdminDeleteConfirmationData(null).message;

        expect(message).toContain('another user');
        expect(message).not.toContain('<strong>');
    });

    it('escapes the owner name and wraps it in <strong>', () => {
        const message = getAdminDeleteConfirmationData('<img src=x>').message;

        expect(message).toContain('<strong>&lt;img src=x&gt;</strong>');
        expect(message).not.toContain('<img');
    });
});
