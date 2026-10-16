import { RecycleBinItem } from '../models/recycle-bin.model';

/**
 * A row expands when it has details or named contents to show. A key-value table's keys are only
 * counted (its Keys column), never listed.
 */
export function isExpandableItem(item: RecycleBinItem): boolean {
    return item.details.length > 0 || item.contents.length > 0;
}
