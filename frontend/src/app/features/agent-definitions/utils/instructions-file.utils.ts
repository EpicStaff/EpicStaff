import { getFileExtension } from '../../files/utils/storage-file.utils';

/**
 * File extensions that can be read directly as text and used as boot
 * instructions. Everything here is safe to pass to `blob.text()` /
 * `FileReader.readAsText`.
 *
 * TODO: `.docx` is intentionally excluded — extracting plain text
 * from a .docx needs a dedicated dependency (e.g. mammoth) or a backend
 * endpoint. `docx-preview` only renders HTML, not text.
 */
export const INSTRUCTIONS_TEXT_EXTENSIONS = [
    'md',
    'markdown',
    'txt',
    'log',
    'json',
    'yaml',
    'yml',
    'csv',
    'xml',
] as const;

/** Value for a native file input's `accept` attribute (e.g. ".md,.txt,..."). */
export const INSTRUCTIONS_ACCEPT_ATTR = INSTRUCTIONS_TEXT_EXTENSIONS.map((ext) => `.${ext}`).join(',');

const EXTENSION_SET = new Set<string>(INSTRUCTIONS_TEXT_EXTENSIONS);

/** True when the file name has an extension we can read as instruction text. */
export function isInstructionsTextFile(name: string): boolean {
    return EXTENSION_SET.has(getFileExtension(name));
}

/** Read a File/Blob as UTF-8 text. */
export function readFileAsText(file: File | Blob): Promise<string> {
    return file.text();
}
