import { movedStorageItemsMessage } from './storage-delete-message.utils';

const FILE = { type: 'file' } as const;
const FOLDER = { type: 'folder' } as const;

describe('movedStorageItemsMessage', () => {
    it.each([
        ['one file', [FILE], 'Moved 1 file to the recycle bin.'],
        ['two files', [FILE, FILE], 'Moved 2 files to the recycle bin.'],
        ['one folder', [FOLDER], 'Moved 1 folder to the recycle bin.'],
        ['three folders', [FOLDER, FOLDER, FOLDER], 'Moved 3 folders to the recycle bin.'],
        ['files and folders', [FILE, FOLDER], 'Moved 2 items to the recycle bin.'],
    ])('%s', (_name, items, expected) => {
        expect(movedStorageItemsMessage(items)).toBe(expected);
    });
});
