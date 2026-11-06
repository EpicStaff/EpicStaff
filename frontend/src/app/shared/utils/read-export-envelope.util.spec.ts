/// <reference types="node" />
// tsconfig.spec.json loads only the Vitest globals' types; the archive fixtures are read with Node's (`@types/node`).
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { storedZip } from './read-export-envelope.testing';
import { readExportEnvelope } from './read-export-envelope.util';

const ENVELOPE = { main_entity: 'Flow', version: 6, Flow: [{ id: 1, name: 'Orders' }] };

describe('readExportEnvelope', () => {
    it('parses a plain JSON export', async () => {
        const file = new File([JSON.stringify(ENVELOPE)], 'flow.json');

        await expect(readExportEnvelope(file)).resolves.toEqual({ format: 'json', data: ENVELOPE });
    });

    it('reads only export.json of an archive', async () => {
        const archive = storedZip('flows.zip', {
            'files/collection-1/report.pdf': 'not json at all',
            'export.json': JSON.stringify(ENVELOPE),
        });

        await expect(readExportEnvelope(archive)).resolves.toEqual({ format: 'zip', data: ENVELOPE });
    });

    it('tells an archive by its content, whatever its name', async () => {
        const archive = storedZip('flows.json', { 'export.json': JSON.stringify(ENVELOPE) });

        await expect(readExportEnvelope(archive)).resolves.toEqual({ format: 'zip', data: ENVELOPE });
    });

    it('rejects an archive without export.json', async () => {
        const archive = storedZip('flows.zip', { 'other.json': JSON.stringify(ENVELOPE) });

        await expect(readExportEnvelope(archive)).rejects.toThrow('The archive has no export.json');
    });

    /*
     * Written by Python's zipfile the way the backend's ExportArchiveWriter writes an export: ZIP_DEFLATED with
     * allowZip64, the archived file through `open(member, 'w', force_zip64=True)`, then export.json with `writestr`.
     * `export-archive-streamed.zip` was written the same way to a stream zipfile cannot seek in, so every member is
     * followed by a data descriptor (flag bit 3).
     */
    it.each(['export-archive.zip', 'export-archive-streamed.zip'])(
        'reads the deflated export.json of an archive the backend writes (%s)',
        async (fixture) => {
            const bytes = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures', fixture));
            const archive = new File([new Uint8Array(bytes)], 'collections.zip');

            await expect(readExportEnvelope(archive)).resolves.toEqual({
                format: 'zip',
                data: {
                    main_entity: 'SourceCollection',
                    version: 6,
                    SourceCollection: [{ id: 3, collection_name: 'Handbook' }],
                },
            });
        }
    );

    it('rejects a file that is not JSON', async () => {
        const file = new File(['not json'], 'flow.json');

        await expect(readExportEnvelope(file)).rejects.toThrow('The file is not a valid export');
    });
});
