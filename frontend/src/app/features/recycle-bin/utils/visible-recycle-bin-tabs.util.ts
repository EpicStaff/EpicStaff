import { ActionCode } from '@shared/models';

import { RECYCLE_BIN_TABS } from '../constants/recycle-bin-tabs.constants';
import { CanFunction, RecycleBinTabDefinition } from '../models/recycle-bin.model';

/** Tabs the caller may see, in page order. A tab needs READ on its resource. */
export function visibleRecycleBinTabs(can: CanFunction): RecycleBinTabDefinition[] {
    return RECYCLE_BIN_TABS.filter((tab) => can(tab.resource, ActionCode.Read));
}

/**
 * A Kind column where the tab has kinds to tell apart: storage rows (file / folder), or the bins of Tools,
 * whose column header holds the switch between them.
 */
export function recycleBinTabShowsKind(tab: RecycleBinTabDefinition): boolean {
    return tab.sources.length > 1 || tab.sources.includes('storage');
}
