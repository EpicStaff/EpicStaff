import { ConfirmationDialogData } from '@shared/components';

import {
    buildBulkSelectedDeleteDialog,
    buildSingleDeleteWithUsageDialog,
    buildUnusedDeleteDialog,
} from './bulk-tool-op.util';

const TOOLS = [
    { id: 1, name: 'Parser', agentSurfaceCount: 1, sharedSurfaceCount: 0, inlineSurfaceCount: 0 },
    { id: 2, name: 'Search', agentSurfaceCount: 0, sharedSurfaceCount: 2, inlineSurfaceCount: 0 },
    { id: 3, name: 'Writer', agentSurfaceCount: 0, sharedSurfaceCount: 0, inlineSurfaceCount: 1 },
];

function dialogText(dialog: ConfirmationDialogData): string {
    return `${dialog.message} ${dialog.caution ?? ''}`;
}

describe('tool delete dialogs', () => {
    it.each([
        ['unused', buildUnusedDeleteDialog(2, 'custom tools', 7)],
        ['single with usage', buildSingleDeleteWithUsageDialog('Parser', 1, 0, 0, 7)],
        ['bulk selected', buildBulkSelectedDeleteDialog(TOOLS, 7)],
    ])('%s: says the tools move to the recycle bin, not that they are gone for good', (_name, dialog) => {
        expect(dialogText(dialog)).not.toMatch(/permanently|cannot be undone/);
        expect(dialogText(dialog)).toContain('recycle bin');
        expect(dialogText(dialog)).toContain('7 days');
    });

    it('speaks of several selected tools in the plural', () => {
        expect(dialogText(buildBulkSelectedDeleteDialog(TOOLS, 7))).toContain('They move to the recycle bin');
    });

    it('says restoring a used tool does not reconnect its surfaces', () => {
        expect(buildSingleDeleteWithUsageDialog('Parser', 1, 0, 0, 7).caution).toContain(
            "restoring it won't reconnect them"
        );
    });

    it('escapes the tool name', () => {
        expect(buildSingleDeleteWithUsageDialog('<i>t</i>', 1, 0, 0, 7).message).toContain('&lt;i&gt;t&lt;/i&gt;');
    });
});
