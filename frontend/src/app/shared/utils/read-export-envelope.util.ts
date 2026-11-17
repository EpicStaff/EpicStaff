import { ImportFileData } from './import-preview.util';

/** The member of an export archive that holds the envelope a plain `.json` export has. */
export const EXPORT_ENVELOPE_MEMBER = 'export.json';

const ZIP_SIGNATURE = [0x50, 0x4b, 0x03, 0x04];

const LOCAL_FILE_HEADER_SIGNATURE = 0x04034b50;
const LOCAL_FILE_HEADER_SIZE = 30;
const CENTRAL_DIRECTORY_HEADER_SIGNATURE = 0x02014b50;
const CENTRAL_DIRECTORY_HEADER_SIZE = 46;
const END_OF_CENTRAL_DIRECTORY_SIGNATURE = 0x06054b50;
const END_OF_CENTRAL_DIRECTORY_SIZE = 22;
const MAX_ARCHIVE_COMMENT_SIZE = 0xffff;
/** A size or offset too large for its 32-bit field; the real value is in a ZIP64 record. */
const ZIP64_MARKER = 0xffffffff;
const ENCRYPTED_FLAG = 0x1;
const STORED_METHOD = 0;
const DEFLATE_METHOD = 8;

export type ExportFileFormat = 'json' | 'zip';

export interface ExportEnvelope {
    /** `zip` for an export archive, `json` for a plain JSON export. */
    format: ExportFileFormat;
    data: ImportFileData;
}

/** Where a member of a zip archive is and how it is stored, from its central directory entry. */
interface ArchiveMember {
    flags: number;
    method: number;
    compressedSize: number;
    localHeaderOffset: number;
}

interface EndOfCentralDirectory {
    directoryOffset: number;
    directorySize: number;
}

/**
 * Reads the export envelope of an import file. A plain JSON export is parsed whole; of a zip
 * archive only `export.json` is read, never the files it carries.
 *
 * Rejects when the JSON cannot be parsed, the archive has no `export.json`, or the archive stores it in a
 * way this reader does not support: encrypted, ZIP64, or compressed other than by deflate.
 */
export async function readExportEnvelope(file: Blob): Promise<ExportEnvelope> {
    if (await isZipArchive(file)) {
        return { format: 'zip', data: parseEnvelope(await readArchiveEnvelope(file)) };
    }
    return { format: 'json', data: parseEnvelope(await file.text()) };
}

/**
 * The envelope as a plain JSON export file, for a request that needs only the envelope, such as an import
 * inspection: the archive's files stay on the user's machine.
 */
export function exportEnvelopeFile(data: ImportFileData): File {
    return new File([JSON.stringify(data)], EXPORT_ENVELOPE_MEMBER, { type: 'application/json' });
}

async function isZipArchive(file: Blob): Promise<boolean> {
    const head = new Uint8Array(await file.slice(0, ZIP_SIGNATURE.length).arrayBuffer());
    return head.length === ZIP_SIGNATURE.length && ZIP_SIGNATURE.every((byte, index) => head[index] === byte);
}

async function readArchiveEnvelope(file: Blob): Promise<string> {
    const envelope = await findArchiveMember(file, EXPORT_ENVELOPE_MEMBER);
    if (!envelope) {
        throw new Error(`The archive has no ${EXPORT_ENVELOPE_MEMBER}. Choose a file exported from EpicStaff.`);
    }
    return readMemberText(file, envelope);
}

/** Looks `name` up in the archive's central directory, the index at the end of a zip. */
async function findArchiveMember(file: Blob, name: string): Promise<ArchiveMember | null> {
    const end = await readEndOfCentralDirectory(file);
    // Walked by its byte size, not its entry count: past 65,535 entries the count is only a ZIP64 marker.
    const directory = await readView(file, end.directoryOffset, end.directorySize);
    const decoder = new TextDecoder();
    let position = 0;
    while (position + CENTRAL_DIRECTORY_HEADER_SIZE <= directory.byteLength) {
        if (directory.getUint32(position, true) !== CENTRAL_DIRECTORY_HEADER_SIGNATURE) {
            throw damagedArchiveError();
        }
        const nameLength = directory.getUint16(position + 28, true);
        const extraLength = directory.getUint16(position + 30, true);
        const commentLength = directory.getUint16(position + 32, true);
        const nameStart = position + CENTRAL_DIRECTORY_HEADER_SIZE;
        if (nameStart + nameLength > directory.byteLength) {
            throw damagedArchiveError();
        }
        const entryName = decoder.decode(
            new Uint8Array(directory.buffer, directory.byteOffset + nameStart, nameLength)
        );
        if (entryName === name) {
            return {
                flags: directory.getUint16(position + 8, true),
                method: directory.getUint16(position + 10, true),
                // Taken from here, not the local header: a member written with a data descriptor has zero sizes there.
                compressedSize: directory.getUint32(position + 20, true),
                localHeaderOffset: directory.getUint32(position + 42, true),
            };
        }
        position += CENTRAL_DIRECTORY_HEADER_SIZE + nameLength + extraLength + commentLength;
    }
    return null;
}

async function readEndOfCentralDirectory(file: Blob): Promise<EndOfCentralDirectory> {
    // The record closes the archive, followed only by a comment of at most 65,535 bytes.
    const tailStart = Math.max(0, file.size - END_OF_CENTRAL_DIRECTORY_SIZE - MAX_ARCHIVE_COMMENT_SIZE);
    const tail = await readView(file, tailStart, file.size - tailStart);
    for (let position = tail.byteLength - END_OF_CENTRAL_DIRECTORY_SIZE; position >= 0; position--) {
        const commentLength = tail.getUint16(position + 20, true);
        const isRecord =
            tail.getUint32(position, true) === END_OF_CENTRAL_DIRECTORY_SIGNATURE &&
            position + END_OF_CENTRAL_DIRECTORY_SIZE + commentLength === tail.byteLength;
        if (!isRecord) {
            continue;
        }
        const directorySize = tail.getUint32(position + 12, true);
        const directoryOffset = tail.getUint32(position + 16, true);
        if (directorySize === ZIP64_MARKER || directoryOffset === ZIP64_MARKER) {
            throw unsupportedArchiveError('it is a ZIP64 archive');
        }
        if (directoryOffset + directorySize > tailStart + position) {
            throw damagedArchiveError();
        }
        return { directoryOffset, directorySize };
    }
    throw damagedArchiveError();
}

async function readMemberText(file: Blob, member: ArchiveMember): Promise<string> {
    if (member.flags & ENCRYPTED_FLAG) {
        throw unsupportedArchiveError(`${EXPORT_ENVELOPE_MEMBER} is encrypted`);
    }
    if (member.compressedSize === ZIP64_MARKER || member.localHeaderOffset === ZIP64_MARKER) {
        throw unsupportedArchiveError(`${EXPORT_ENVELOPE_MEMBER} is stored as ZIP64`);
    }
    const header = await readView(file, member.localHeaderOffset, LOCAL_FILE_HEADER_SIZE);
    if (header.byteLength < LOCAL_FILE_HEADER_SIZE || header.getUint32(0, true) !== LOCAL_FILE_HEADER_SIGNATURE) {
        throw damagedArchiveError();
    }
    // The local name and extra field may differ in length from the central directory's.
    const dataStart =
        member.localHeaderOffset + LOCAL_FILE_HEADER_SIZE + header.getUint16(26, true) + header.getUint16(28, true);
    const dataEnd = dataStart + member.compressedSize;
    if (dataEnd > file.size) {
        throw damagedArchiveError();
    }
    const data = file.slice(dataStart, dataEnd);

    switch (member.method) {
        case STORED_METHOD:
            return data.text();
        case DEFLATE_METHOD:
            return inflateText(data);
        default:
            throw unsupportedArchiveError(`${EXPORT_ENVELOPE_MEMBER} uses compression method ${member.method}`);
    }
}

async function inflateText(deflated: Blob): Promise<string> {
    // Read whole instead of through `Blob.stream()`: the envelope is small, and jsdom's Blob, which the tests
    // run on, has no `stream()`.
    const compressed = new Response(await deflated.arrayBuffer()).body;
    try {
        return await new Response(compressed?.pipeThrough(new DecompressionStream('deflate-raw'))).text();
    } catch {
        throw damagedArchiveError();
    }
}

async function readView(file: Blob, start: number, length: number): Promise<DataView> {
    return new DataView(await file.slice(start, start + length).arrayBuffer());
}

function damagedArchiveError(): Error {
    return new Error('The archive is damaged. Choose a file exported from EpicStaff.');
}

function unsupportedArchiveError(reason: string): Error {
    return new Error(`The archive cannot be read: ${reason}. Choose a file exported from EpicStaff.`);
}

function parseEnvelope(text: string): ImportFileData {
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch {
        throw new Error('The file is not a valid export. Choose a file exported from EpicStaff.');
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('The file is not a valid export. Choose a file exported from EpicStaff.');
    }
    return parsed as ImportFileData;
}
