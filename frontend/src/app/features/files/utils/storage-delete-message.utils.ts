import { movedToRecycleBinMessage } from '@shared/utils';

import { StorageItem } from '../models/storage.models';

/**
 * Success toast of a storage delete. Names files or folders when the items are all of one type,
 * otherwise "items".
 */
export function movedStorageItemsMessage(items: readonly Pick<StorageItem, 'type'>[]): string {
    const count = items.length;
    if (items.every((item) => item.type === 'file')) return movedToRecycleBinMessage(count, 'file', 'files');
    if (items.every((item) => item.type === 'folder')) return movedToRecycleBinMessage(count, 'folder', 'folders');
    return movedToRecycleBinMessage(count, 'item', 'items');
}
