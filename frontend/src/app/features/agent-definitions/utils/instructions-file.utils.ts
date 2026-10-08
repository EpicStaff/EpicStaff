import { getFileExtension } from '../../files/utils/storage-file.utils';
import { AgentInstruction } from '../models/agent-definition.model';

/** Same wording as the backend's validation error, so both surface identically. */
export const DUPLICATE_INSTRUCTION_NAME_MESSAGE =
    'An instruction with that name already exists. Please enter a unique name.';

/**
 * File extensions that can be read directly as text and used as agent
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

/** Names are unique per agent, compared case-insensitively (mirrors the backend rule). */
export function isInstructionNameTaken(name: string, list: AgentInstruction[], ignoreIndex = -1): boolean {
    const wanted = name.trim().toLowerCase();
    return list.some((instruction, index) => index !== ignoreIndex && instruction.name.toLowerCase() === wanted);
}

/** First free `Instruction_N.md`, starting at N = list length + 1. */
export function nextDefaultInstructionName(list: AgentInstruction[]): string {
    let number = list.length + 1;
    while (isInstructionNameTaken(`Instruction_${number}.md`, list)) number++;
    return `Instruction_${number}.md`;
}

/** `name` itself when free, else `base_2.ext`, `base_3.ext`, … */
export function uniqueInstructionName(name: string, list: AgentInstruction[]): string {
    if (!isInstructionNameTaken(name, list)) return name;
    const dotIndex = name.lastIndexOf('.');
    const base = dotIndex > 0 ? name.slice(0, dotIndex) : name;
    const extension = dotIndex > 0 ? name.slice(dotIndex) : '';
    let suffix = 2;
    while (isInstructionNameTaken(`${base}_${suffix}${extension}`, list)) suffix++;
    return `${base}_${suffix}${extension}`;
}
