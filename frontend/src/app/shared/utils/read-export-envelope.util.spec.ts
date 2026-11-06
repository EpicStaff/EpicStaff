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

    it('rejects a file that is not JSON', async () => {
        const file = new File(['not json'], 'flow.json');

        await expect(readExportEnvelope(file)).rejects.toThrow('The file is not a valid export');
    });
});
