import { RecycleBinItem } from '../models/recycle-bin.model';

/**
 * A row expands when it has details or named contents to show. A key-value table's keys are only
 * counted (its Keys column), never listed.
 */
export function isExpandableItem(item: RecycleBinItem): boolean {
    return item.details.length > 0 || item.contents.length > 0;
}

/**
 * Named contents the backend counted but didn't send (it lists at most 100): what "Show all" can still
 * bring. Hidden contents are counted in the total too, but "Show all" never lists them.
 */
export function unlistedContentsCount(item: RecycleBinItem): number {
    return Math.max(0, item.contentsTotal - item.contents.length - item.hiddenContentsCount);
}
