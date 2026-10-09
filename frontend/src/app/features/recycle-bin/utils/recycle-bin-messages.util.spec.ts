import { HttpErrorResponse } from '@angular/common/http';

import { RECYCLE_BIN_TAB_BY_KEY } from '../constants/recycle-bin-tabs.constants';
import { RecycleBinItem } from '../models/recycle-bin.model';
import {
    bulkActionErrorMessage,
    emptyRecycleBinConfirmationDialog,
    failedItemsMessage,
    purgeConfirmationDialog,
    purgeConfirmationMessage,
    purgeResultMessage,
    purgeSelectedConfirmationDialog,
    recycleBinActionErrorMessage,
    restoreResultMessage,
    restoreSuccessMessage,
} from './recycle-bin-messages.util';

function httpError(status: number, body: unknown = null): HttpErrorResponse {
    return new HttpErrorResponse({ status, error: body });
}

function binItem(source: RecycleBinItem['source'], name: string): RecycleBinItem {
    return {
        key: `${source}-1`,
        id: 1,
        source,
        name,
        displayName: name,
        kind: '',
        deletedAt: new Date(),
        daysLeft: 3,
        details: [],
        contents: [],
        contentsTotal: 0,
    };
}

describe('recycle bin messages', () => {
    it('says an item was restored, without its links', () => {
        expect(restoreSuccessMessage({ source: 'flow', name: 'Report', renamedFrom: null })).toBe(
            `"Report" restored. Its links to other items aren't restored.`
        );
    });

    it('says a secret, voice channel or webhook trigger comes back connected', () => {
        expect(restoreSuccessMessage({ source: 'secret', name: 'API_KEY', renamedFrom: null })).toBe(
            `"API_KEY" restored. Everything that used it is connected again.`
        );
        expect(
            restoreResultMessage({
                restored: [
                    { source: 'webhook_trigger', name: 'orders', renamedFrom: null },
                    { source: 'webhook_trigger', name: 'calls', renamedFrom: null },
                ],
                failed: [],
            })
        ).toBe(`2 restored. Everything that used them is connected again.`);
    });

    it('names the new name when the restore had to rename', () => {
        expect(restoreSuccessMessage({ source: 'flow', name: 'Report #2', renamedFrom: 'Report' })).toBe(
            `"Report" restored as "Report #2", because that name was taken. Its links to other items aren't restored.`
        );
    });

    it('explains a 404 as an item already gone from the bin', () => {
        expect(recycleBinActionErrorMessage(httpError(404), 'restore', 'Report')).toBe(
            'This item is no longer in the recycle bin.'
        );
    });

    it('leaves a 403 to the forbidden interceptor', () => {
        expect(recycleBinActionErrorMessage(httpError(403), 'delete', 'Report')).toBeNull();
    });

    it('falls back to a retry hint for anything else', () => {
        expect(recycleBinActionErrorMessage(httpError(500), 'delete', 'Report')).toBe(
            `Couldn't delete "Report". Please try again.`
        );
    });

    it('escapes the name in the purge confirmation', () => {
        expect(purgeConfirmationMessage(binItem('flow', '<img src=x>'))).toBe(
            `<strong>&lt;img src=x&gt;</strong> will be deleted for good. You can't undo this.`
        );
    });

    it('warns that purging a folder takes what was deleted with it', () => {
        expect(purgeConfirmationMessage(binItem('storage', 'docs/'))).toContain(
            'Everything that was deleted with it goes too.'
        );
    });

    it('builds a plain permanent-delete dialog, with no phrase to type', () => {
        const dialog = purgeConfirmationDialog(binItem('flow', 'Report'));
        expect(dialog.verification).toBeUndefined();
        expect(dialog.type).toBe('danger');
        expect(dialog.message).toBe(`<strong>Report</strong> will be deleted for good. You can't undo this.`);
    });

    it('keeps the full path of a storage item in the body', () => {
        const dialog = purgeConfirmationDialog(binItem('storage', 'docs/reports/a.txt'));
        expect(dialog.message).toContain('<strong>docs/reports/a.txt</strong>');
    });

    describe('bulk', () => {
        it('lists the first three names and how many more in the delete dialog', () => {
            const dialog = purgeSelectedConfirmationDialog(['a', 'b', '<c>', 'd', 'e']);
            expect(dialog.message).toContain(
                '<strong>a</strong>, <strong>b</strong>, <strong>&lt;c&gt;</strong> and 2 more'
            );
        });

        it('joins two names with "and"', () => {
            expect(purgeSelectedConfirmationDialog(['a', 'b']).message).toContain(
                '<strong>a</strong> and <strong>b</strong> will be deleted'
            );
        });

        it('asks to type a phrase only to empty the whole bin', () => {
            expect(purgeSelectedConfirmationDialog(['a', 'b']).verification).toBeUndefined();
            const emptyBin = emptyRecycleBinConfirmationDialog([
                RECYCLE_BIN_TAB_BY_KEY.flows,
                RECYCLE_BIN_TAB_BY_KEY.tools,
            ]);
            expect(emptyBin.verification).toEqual({ phrase: 'empty-recycle-bin' });
            expect(emptyBin.message).toContain('<strong>Flows</strong>, <strong>Tools</strong>');
        });

        it('sums up a restore with its renames, and keeps the single-item wording for one', () => {
            expect(
                restoreResultMessage({
                    restored: [
                        { source: 'flow', name: 'Report #2', renamedFrom: 'Report' },
                        { source: 'flow', name: 'a', renamedFrom: null },
                        { source: 'flow', name: 'b', renamedFrom: null },
                        { source: 'flow', name: 'c', renamedFrom: null },
                        { source: 'flow', name: 'd', renamedFrom: null },
                    ],
                    failed: [],
                })
            ).toBe(`5 restored, 1 renamed: Report → Report #2. Their links to other items aren't restored.`);
            expect(
                restoreResultMessage({ restored: [{ source: 'flow', name: 'a', renamedFrom: null }], failed: [] })
            ).toBe(`"a" restored. Its links to other items aren't restored.`);
            expect(restoreResultMessage({ restored: [], failed: [] })).toBeNull();
        });

        it('sums up a purge', () => {
            expect(purgeResultMessage({ purgedCount: 1, failed: [] }, 'Report')).toBe('"Report" deleted permanently.');
            expect(purgeResultMessage({ purgedCount: 4, failed: [] })).toBe('4 items deleted permanently.');
            expect(purgeResultMessage({ purgedCount: 0, failed: [] })).toBeNull();
        });

        it('lists the first three failures with their reasons', () => {
            const failed = ['a', 'b', 'c', 'd'].map((name) => ({ name, message: 'Locked.' }));
            expect(failedItemsMessage('restore', failed)).toBe(
                `Couldn't restore 4 items. "a": Locked. "b": Locked. "c": Locked. …and 1 more.`
            );
            expect(failedItemsMessage('delete', [])).toBeNull();
        });

        it('explains a 404 of a bulk call, and leaves a 403 to the interceptor', () => {
            expect(bulkActionErrorMessage(httpError(404), 'restore')).toBe(
                'Some of these items are no longer in the recycle bin. The list has been refreshed.'
            );
            expect(bulkActionErrorMessage(httpError(403), 'delete')).toBeNull();
        });
    });
});
