import { ImportFileData } from './import-preview.util';

/** The member of an export archive that holds the envelope a plain `.json` export has. */
export const EXPORT_ENVELOPE_MEMBER = 'export.json';

const ZIP_SIGNATURE = [0x50, 0x4b, 0x03, 0x04];

export type ExportFileFormat = 'json' | 'zip';

export interface ExportEnvelope {
    /** `zip` for an export archive, `json` for a plain JSON export. */
    format: ExportFileFormat;
    data: ImportFileData;
}

/**
 * Reads the export envelope of an import file. A plain JSON export is parsed whole; of a zip
 * archive only `export.json` is read, never the files it carries.
 *
 * Rejects when the JSON cannot be parsed or the archive has no `export.json`.
 */
export async function readExportEnvelope(file: Blob): Promise<ExportEnvelope> {
    if (await isZipArchive(file)) {
        return { format: 'zip', data: parseEnvelope(await readArchiveEnvelope(file)) };
    }
    return { format: 'json', data: parseEnvelope(await file.text()) };
}

async function isZipArchive(file: Blob): Promise<boolean> {
    const head = new Uint8Array(await file.slice(0, ZIP_SIGNATURE.length).arrayBuffer());
    return head.length === ZIP_SIGNATURE.length && ZIP_SIGNATURE.every((byte, index) => head[index] === byte);
}

async function readArchiveEnvelope(file: Blob): Promise<string> {
    // Loaded on demand: only an archive import needs the zip reader.
    const { BlobReader, TextWriter, ZipReader } = await import('@zip.js/zip.js');
    // The envelope is small, so it is inflated here rather than in a web worker.
    const reader = new ZipReader(new BlobReader(file), { useWebWorkers: false });
    try {
        const entries = await reader.getEntries();
        const envelope = entries.find((entry) => entry.filename === EXPORT_ENVELOPE_MEMBER);
        if (!envelope || envelope.directory) {
            throw new Error(`The archive has no ${EXPORT_ENVELOPE_MEMBER}. Choose a file exported from EpicStaff.`);
        }
        return await envelope.getData(new TextWriter());
    } finally {
        await reader.close();
    }
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
