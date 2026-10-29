import { ActionCode, ResourceCode } from '@shared/models';

import { RECYCLE_BIN_TABS } from '../constants/recycle-bin-tabs.constants';
import { CanFunction } from '../models/recycle-bin.model';
import { recycleBinTabShowsKind, visibleRecycleBinTabs } from './visible-recycle-bin-tabs.util';

function canFrom(grants: [ResourceCode, ActionCode][]): CanFunction {
    return (resource, action) =>
        grants.some(([grantedResource, grantedAction]) => grantedResource === resource && grantedAction === action);
}

function visibleKeys(can: CanFunction): string[] {
    return visibleRecycleBinTabs(can).map((tab) => tab.key);
}

describe('visibleRecycleBinTabs', () => {
    it('shows no tab without any permission', () => {
        expect(visibleRecycleBinTabs(() => false)).toEqual([]);
    });

    it('shows every tab in page order with every permission', () => {
        expect(visibleKeys(() => true)).toEqual([
            'flows',
            'agents',
            'surfaces',
            'tools',
            'files',
            'knowledge-sources',
            'key-value-tables',
            'secrets',
            'voice-channels',
            'webhook-triggers',
        ]);
    });

    it('follows the page order, not the order of the grants', () => {
        const can = canFrom([
            [ResourceCode.Files, ActionCode.Read],
            [ResourceCode.Tools, ActionCode.Read],
        ]);
        expect(visibleKeys(can)).toEqual(['tools', 'files']);
    });

    it('needs READ: CREATE and DELETE alone do not show a tab', () => {
        const can = canFrom([
            [ResourceCode.Flows, ActionCode.Create],
            [ResourceCode.Flows, ActionCode.Delete],
        ]);
        expect(visibleKeys(can)).toEqual([]);
    });

    it('shows the Key-value tables tab only with READ on key-value tables', () => {
        const readOnly = canFrom([[ResourceCode.KeyValueTables, ActionCode.Read]]);
        expect(visibleKeys(readOnly)).toEqual(['key-value-tables']);

        const writeOnly = canFrom([
            [ResourceCode.KeyValueTables, ActionCode.Create],
            [ResourceCode.KeyValueTables, ActionCode.Delete],
        ]);
        expect(visibleKeys(writeOnly)).toEqual([]);
    });

    it.each([
        [ResourceCode.Secrets, 'secrets'],
        [ResourceCode.Voice, 'voice-channels'],
        [ResourceCode.Webhooks, 'webhook-triggers'],
    ])('shows a settings tab only with READ on its resource (%s)', (resource, key) => {
        expect(visibleKeys(canFrom([[resource, ActionCode.Read]]))).toEqual([key]);
        expect(visibleKeys(canFrom([[resource, ActionCode.Delete]]))).toEqual([]);
    });
});

describe('recycleBinTabShowsKind', () => {
    it('shows Kind only on tabs whose rows can differ in kind', () => {
        const tabsWithKind = RECYCLE_BIN_TABS.filter(recycleBinTabShowsKind).map((tab) => tab.key);
        expect(tabsWithKind).toEqual(['tools', 'files']);
    });
});
