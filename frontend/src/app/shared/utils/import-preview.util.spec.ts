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

describe('buildPreviewImportResult entity names', () => {
    it.each<{ entityType: string; entity: ImportFileEntity; expectedName: string }>([
        {
            entityType: 'SourceCollection',
            entity: { id: 7, collection_name: 'Handbook (all chunk strategies)', collection_origin: 'user' },
            expectedName: 'Handbook (all chunk strategies)',
        },
        {
            entityType: 'EmbeddingConfig',
            entity: { id: 3, custom_name: 'text-embedding-3-small', model: 2 },
            expectedName: 'text-embedding-3-small',
        },
        {
            entityType: 'RealtimeTranscriptionConfig',
            entity: { id: 4, custom_name: 'Meeting transcriber' },
            expectedName: 'Meeting transcriber',
        },
        { entityType: 'SystemOneConfig', entity: { id: 5, custom_name: 'Router' }, expectedName: 'Router' },
        {
            entityType: 'OpenAIRealtimeConfig',
            entity: { id: 6, custom_name: 'Voice desk' },
            expectedName: 'Voice desk',
        },
        {
            entityType: 'ElevenLabsRealtimeConfig',
            entity: { id: 8, custom_name: 'Narrator' },
            expectedName: 'Narrator',
        },
        {
            entityType: 'GeminiRealtimeConfig',
            entity: { id: 9, custom_name: 'Live helper' },
            expectedName: 'Live helper',
        },
        { entityType: 'LLMConfig', entity: { id: 1, custom_name: 'Writer' }, expectedName: 'Writer' },
        { entityType: 'WebhookTrigger', entity: { id: 2, path: 'orders/new' }, expectedName: 'orders/new' },
        { entityType: 'Flow', entity: { id: 10, name: 'Onboarding' }, expectedName: 'Onboarding' },
    ])('names a $entityType after its own name field', ({ entityType, entity, expectedName }) => {
        const item = buildPreviewImportResult({ [entityType]: [entity] })[entityType]?.created.items[0];

        expect(item?.name).toBe(expectedName);
    });

    it('calls an entity with no name Untitled', () => {
        const item = buildPreviewImportResult({ SourceCollection: [{ id: 7 }] })['SourceCollection']?.created.items[0];

        expect(item?.name).toBe('Untitled');
    });
});
