import { describe, expect, it } from 'vitest';

import { ImportResultItem } from '../../core/models/import-result.model';
import { buildPreviewImportResult, ImportFileEntity } from './import-preview.util';

function previewedConfig(config: ImportFileEntity): ImportResultItem | undefined {
    return buildPreviewImportResult({ LLMConfig: [config] })['LLMConfig']?.created.items[0];
}

describe('buildPreviewImportResult LLM config fields', () => {
    it.each<{ fileVersion: string; config: ImportFileEntity }>([
        {
            fileVersion: 'version 6, settings under parameters',
            config: {
                id: 1,
                custom_name: 'Writer',
                timeout: 60,
                parameters: { temperature: 0.2, max_tokens: 2048 },
                connection: {},
            },
        },
        {
            fileVersion: 'version 5, flat settings',
            config: { id: 1, custom_name: 'Writer', timeout: 60, temperature: 0.2, max_tokens: 2048 },
        },
    ])('shows temperature and max tokens of a $fileVersion file', ({ config }) => {
        const item = previewedConfig(config);

        expect(item).toMatchObject({ name: 'Writer', temperature: 0.2, max_tokens: 2048, timeout: 60 });
    });

    it('shows no temperature for a config whose model has none', () => {
        const config: ImportFileEntity = { id: 1, custom_name: 'Reasoner', parameters: { max_tokens: 2048 } };

        const item = previewedConfig(config);

        expect(item).not.toHaveProperty('temperature');
    });
});
