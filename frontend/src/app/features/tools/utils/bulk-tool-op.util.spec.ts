import { DestroyRef, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { of } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { ToolsViewStorageService } from '../services/tools-view-storage.service';
import {
    buildBulkSelectedDeleteDialog,
    buildSingleDeleteWithUsageDialog,
    buildUnusedDeleteDialog,
    runBulkDeleteWithConfirm,
} from './bulk-tool-op.util';

const TOOLS = [
    { id: 1, name: 'Parser', agentSurfaceCount: 1, sharedSurfaceCount: 0, inlineSurfaceCount: 0 },
    { id: 2, name: 'Search', agentSurfaceCount: 0, sharedSurfaceCount: 2, inlineSurfaceCount: 0 },
    { id: 3, name: 'Writer', agentSurfaceCount: 0, sharedSurfaceCount: 0, inlineSurfaceCount: 1 },
];
const UNUSED_TOOLS = [
    { id: 4, name: 'Idle', agentSurfaceCount: 0, sharedSurfaceCount: 0, inlineSurfaceCount: 0 },
    { id: 5, name: 'Spare', agentSurfaceCount: 0, sharedSurfaceCount: 0, inlineSurfaceCount: 0 },
];

function dialogText(dialog: ConfirmationDialogData): string {
    return `${dialog.message} ${dialog.caution ?? ''}`;
}

describe('tool delete dialogs', () => {
    it.each([
        ['unused', buildUnusedDeleteDialog(2, 'custom tool', 'custom tools', 7)],
        ['single with usage', buildSingleDeleteWithUsageDialog('Parser', 1, 0, 0, 7)],
        ['bulk selected', buildBulkSelectedDeleteDialog(TOOLS, 7)],
        ['bulk selected, all unused', buildBulkSelectedDeleteDialog(UNUSED_TOOLS, 7)],
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

    describe('bulk selected', () => {
        it('gives unused tools a plain confirmation, without a dependency warning or usage lines', () => {
            const dialog = buildBulkSelectedDeleteDialog(UNUSED_TOOLS, 7);

            expect(dialog.message).toBe(
                'You are about to delete <strong>2 tools</strong>. ' +
                    'They move to the recycle bin, where you can restore them for 7 days.'
            );
            expect(dialog.caution).toBeUndefined();
        });

        it('warns about dependencies and lists only the tools that are used', () => {
            const dialog = buildBulkSelectedDeleteDialog([...UNUSED_TOOLS, TOOLS[0]], 7);

            expect(dialog.message).toContain('This breaks existing dependencies');
            expect(dialog.caution).toContain('<strong>Parser</strong> is connected to');
            expect(dialog.caution).toContain('1 of them is in use.');
            expect(dialog.caution).not.toContain('Idle');
            expect(dialog.caution).not.toContain('Spare');
        });

        it('lists the most used tool first', () => {
            const caution = buildBulkSelectedDeleteDialog(TOOLS, 7).caution ?? '';

            expect(caution.indexOf('Search')).toBeLessThan(caution.indexOf('Parser'));
        });

        it('speaks of one selected tool in the singular', () => {
            const dialog = buildBulkSelectedDeleteDialog([UNUSED_TOOLS[0]], 7);

            expect(dialog.title).toBe('Delete Tool?');
            expect(dialog.message).toContain('<strong>1 tool</strong>');
        });
    });

    it.each([
        [1, 'Delete unused tool?', '<strong>1 MCP tool</strong>'],
        [3, 'Delete unused tools?', '<strong>3 MCP tools</strong>'],
    ])('titles the unused-tools dialog as a question for %i tool(s)', (count, title, countText) => {
        const dialog = buildUnusedDeleteDialog(count, 'MCP tool', 'MCP tools', 7);

        expect(dialog.title).toBe(title);
        expect(dialog.message).toContain(countText);
    });
});

describe('runBulkDeleteWithConfirm', () => {
    it.each([
        [1, 'Moved 1 MCP tool to the recycle bin.'],
        [3, 'Moved 3 MCP tools to the recycle bin.'],
    ])('removes the deleted tools and says %i moved to the recycle bin', (deleted, expected) => {
        const toast = { success: vi.fn(), error: vi.fn() };
        const allTools = signal([{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]);
        const ids = [1, 2, 3].slice(0, deleted);

        runBulkDeleteWithConfirm(ids, {
            destroyRef: TestBed.inject(DestroyRef),
            toast: toast as unknown as ToastService,
            confirmation: { confirm: () => of(true) } as unknown as ConfirmationDialogService,
            viewState: { clearSelection: () => undefined } as unknown as ToolsViewStorageService,
            allTools,
            bulkDelete: () => of({ deleted, ids }),
            dialogData: buildUnusedDeleteDialog(deleted, 'MCP tool', 'MCP tools', 7),
            entityLabel: 'MCP tool',
            entityLabelPlural: 'MCP tools',
            scopeLabel: 'selected',
        });

        expect(toast.success).toHaveBeenCalledWith(expected);
        expect(allTools().map((tool) => tool.id)).toEqual([1, 2, 3, 4].slice(deleted));
    });
});
