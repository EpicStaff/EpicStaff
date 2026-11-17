/// <reference types="node" />
// tsconfig.spec.json loads only the Vitest globals' types; the archive fixtures are read with Node's (`@types/node`).
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { storedZip, zipArchive, ZipFixtureMember, ZipFixtureOptions } from './read-export-envelope.testing';
import { readExportEnvelope } from './read-export-envelope.util';

const ENVELOPE = { main_entity: 'Flow', version: 6, Flow: [{ id: 1, name: 'Orders' }] };

describe('readExportEnvelope', () => {
    it('parses a plain JSON export', async () => {
        const file = new File([JSON.stringify(ENVELOPE)], 'flow.json');

        await expect(readExportEnvelope(file)).resolves.toEqual({ format: 'json', data: ENVELOPE });
    });

    it.each<{ case: string; members: ZipFixtureMember[] }>([
        { case: 'deflated', members: [{ name: 'export.json', content: JSON.stringify(ENVELOPE), method: 8 }] },
        { case: 'stored', members: [{ name: 'export.json', content: JSON.stringify(ENVELOPE), method: 0 }] },
        {
            case: 'after other files',
            members: [
                { name: 'files/', content: '' },
                { name: 'files/collection-1/report.pdf', content: 'not json at all', method: 8 },
                { name: 'files/collection-1/export.json', content: '{"main_entity": "Other"}' },
                { name: 'export.json', content: JSON.stringify(ENVELOPE), method: 8 },
            ],
        },
        {
            case: 'deflated, sizes in a data descriptor',
            members: [{ name: 'export.json', content: JSON.stringify(ENVELOPE), method: 8, dataDescriptor: true }],
        },
        {
            case: 'stored, sizes in a data descriptor',
            members: [
                { name: 'notes.txt', content: 'first', dataDescriptor: true },
                { name: 'export.json', content: JSON.stringify(ENVELOPE), dataDescriptor: true },
            ],
        },
    ])('reads export.json of an archive: $case', async ({ members }) => {
        const archive = await zipArchive('flows.zip', members);

        await expect(readExportEnvelope(archive)).resolves.toEqual({ format: 'zip', data: ENVELOPE });
    });

    it('reads a non-ASCII envelope as UTF-8', async () => {
        const envelope = { main_entity: 'Flow', version: 6, Flow: [{ id: 1, name: 'Заказы – 注文' }] };
        const archive = await zipArchive('flows.zip', [
            { name: 'export.json', content: JSON.stringify(envelope), method: 8 },
        ]);

        await expect(readExportEnvelope(archive)).resolves.toEqual({ format: 'zip', data: envelope });
    });

    it('tells an archive by its content, whatever its name', async () => {
        const archive = storedZip('flows.json', { 'export.json': JSON.stringify(ENVELOPE) });

        await expect(readExportEnvelope(archive)).resolves.toEqual({ format: 'zip', data: ENVELOPE });
    });

    it.each(['other.json', 'files/export.json', 'export.json/', 'EXPORT.JSON'])(
        'rejects an archive whose only member is %s',
        async (name) => {
            const archive = storedZip('flows.zip', { [name]: JSON.stringify(ENVELOPE) });

            await expect(readExportEnvelope(archive)).rejects.toThrow(
                'The archive has no export.json. Choose a file exported from EpicStaff.'
            );
        }
    );

    it.each<{ case: string; member: ZipFixtureMember; error: string }>([
        {
            case: 'compressed with an unsupported method',
            member: { name: 'export.json', content: JSON.stringify(ENVELOPE), method: 12 },
            error: 'The archive cannot be read: export.json uses compression method 12.',
        },
        {
            case: 'encrypted',
            member: { name: 'export.json', content: JSON.stringify(ENVELOPE), encrypted: true },
            error: 'The archive cannot be read: export.json is encrypted.',
        },
    ])('rejects export.json $case', async ({ member, error }) => {
        const archive = await zipArchive('flows.zip', [member]);

        await expect(readExportEnvelope(archive)).rejects.toThrow(error);
    });

    it('rejects an archive cut short before its central directory', async () => {
        const archive = storedZip('flows.zip', { 'export.json': JSON.stringify(ENVELOPE) });
        const truncated = archive.slice(0, archive.size - 30);

        await expect(readExportEnvelope(truncated)).rejects.toThrow(
            'The archive is damaged. Choose a file exported from EpicStaff.'
        );
    });

    const DAMAGED = 'The archive is damaged. Choose a file exported from EpicStaff.';
    const ENVELOPE_JSON = JSON.stringify(ENVELOPE);
    /** The central directory entry of a lone `export.json`: the fixed header and the 11-byte name. */
    const LONE_ENTRY_SIZE = 46 + 'export.json'.length;

    it.each<{ case: string; member: Partial<ZipFixtureMember>; options?: ZipFixtureOptions; error: string | null }>([
        {
            case: 'a comment holding a fake end of central directory signature',
            member: { method: 8 },
            options: { comment: `note PK\u0005\u0006${'\u0000'.repeat(18)} end` },
            error: null,
        },
        {
            case: 'entry counts of 0xFFFF, as a ZIP64 archive writes them, over a real directory',
            member: { method: 8 },
            options: { endOverrides: { entryCount: 0xffff } },
            error: null,
        },
        {
            case: 'a local extra field longer than the central one',
            member: { method: 8, localExtraLength: 28 },
            error: null,
        },
        {
            case: 'a central directory offset of 0xFFFFFFFF',
            member: {},
            options: { endOverrides: { directoryOffset: 0xffffffff } },
            error: 'The archive cannot be read: it is a ZIP64 archive.',
        },
        {
            case: 'a member offset of 0xFFFFFFFF',
            member: { centralOverrides: { localHeaderOffset: 0xffffffff } },
            error: 'The archive cannot be read: export.json is stored as ZIP64.',
        },
        {
            case: 'a central directory that runs into the end of central directory record',
            member: {},
            options: { endOverrides: { directorySize: LONE_ENTRY_SIZE + 1 } },
            error: DAMAGED,
        },
        {
            case: 'a central directory that ends inside an entry name',
            member: {},
            options: { endOverrides: { directorySize: LONE_ENTRY_SIZE - 4 } },
            error: DAMAGED,
        },
        {
            case: 'corrupt deflate data',
            member: { method: 8, rawData: new Uint8Array([0xff, 0xff, 0xff, 0xff]) },
            error: DAMAGED,
        },
        {
            case: 'member data running past the end of the file',
            member: { centralOverrides: { compressedSize: 100_000 } },
            error: DAMAGED,
        },
    ])('reads or rejects an archive with $case', async ({ member, options, error }) => {
        const archive = await zipArchive(
            'flows.zip',
            [{ name: 'export.json', content: ENVELOPE_JSON, ...member }],
            options
        );

        if (error === null) {
            await expect(readExportEnvelope(archive)).resolves.toEqual({ format: 'zip', data: ENVELOPE });
        } else {
            await expect(readExportEnvelope(archive)).rejects.toThrow(error);
        }
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
