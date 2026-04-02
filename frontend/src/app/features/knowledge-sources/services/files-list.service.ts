import { Injectable } from '@angular/core';

import { FILE_TYPES, MAX_DOCUMENT_SIZE } from '../constants/constants';
import { DisplayedListDocument } from '../models/document.model';

@Injectable({
    providedIn: 'root',
})
export class FileListService {
    private readonly allowedTypes = FILE_TYPES;

    filterValidFiles(files: File[]): File[] {
        return files.filter((file) => {
            const type = file.name.split('.').pop();
            return !!type && this.allowedTypes.includes(type) && file.size < MAX_DOCUMENT_SIZE;
        });
    }

    transformFilesToDisplayedDocuments(files: File[], collectionId: number): DisplayedListDocument[] {
        return files.map((file: File) => {
            const type = file.name.split('.').pop();
            const isValidType = !!type && this.allowedTypes.includes(type);
            const isValidSize = file.size < MAX_DOCUMENT_SIZE;

            return {
                file_name: file.name,
                file_size: file.size,
                source_collection: collectionId,
                isValidType,
                isValidSize,
            };
        });
    }

    filterDuplicatesByName(files: FileList, existingFiles: DisplayedListDocument[]): File[] {
        const arr: File[] = [];
        const existingNames = new Set(existingFiles.map((f) => f.file_name));

        for (const file of Array.from(files)) {
            if (existingNames.has(file.name)) continue;
            if (arr.some((f) => f.name === file.name)) continue;

            arr.push(file);
            existingNames.add(file.name);
        }
        return arr;
    }
}
