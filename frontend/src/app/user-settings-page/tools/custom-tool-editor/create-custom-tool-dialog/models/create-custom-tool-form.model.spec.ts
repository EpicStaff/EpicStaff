import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { GetPythonCodeToolRequest, toSecretIds } from '@shared/models';

import { CustomToolsService } from '../../../../../features/tools/services/custom-tools/custom-tools.service';
import { ConfigService } from '../../../../../services/config';
import { toCreatePayload } from './create-custom-tool-form.model';

// A tool exactly as `GET /python-code-tool/{id}/` returns it, read-only fields included.
const LOADED_TOOL: GetPythonCodeToolRequest = {
    id: 7,
    python_code: {
        id: 70,
        code: 'def main():\n    return 1\n',
        entrypoint: 'main',
        libraries: ['requests'],
        secrets: [{ id: 4, name: 'API_TOKEN' }],
    },
    name: 'Fetch orders',
    description: 'Fetches the latest orders',
    args_schema: { title: 'ArgsSchema', type: 'object', properties: {} },
    built_in: false,
    variables: [{ name: 'limit', type: 'integer' }],
    use_storage: true,
    is_favorite: true,
    labels: [3],
    created_at: '2026-09-15T08:00:00Z',
    updated_at: '2026-10-01T09:30:00Z',
    created_by: { id: 2, display_name: 'Grace Hopper', avatar_url: null },
    last_edited_by: { id: 3, display_name: 'Ada Lovelace', avatar_url: 'https://example.com/avatars/3.png' },
    last_edited_at: '2026-10-01T09:30:00Z',
};

const READ_ONLY_KEYS = [
    'id',
    'built_in',
    'is_favorite',
    'labels',
    'args_schema',
    'created_by',
    'created_at',
    'updated_at',
    'last_edited_by',
    'last_edited_at',
];

describe('toCreatePayload sent through CustomToolsService', () => {
    let service: CustomToolsService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(CustomToolsService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('does not send the read-only fields back when a loaded tool is saved unchanged', () => {
        // The edit dialog seeds its form from the loaded tool and builds the body with toCreatePayload.
        const payload = toCreatePayload(
            {
                name: LOADED_TOOL.name,
                description: LOADED_TOOL.description,
                pythonCode: LOADED_TOOL.python_code.code,
                variablesJson: JSON.stringify(LOADED_TOOL.variables),
                libraries: LOADED_TOOL.python_code.libraries,
                useStorage: LOADED_TOOL.use_storage ?? false,
            },
            toSecretIds(LOADED_TOOL.python_code.secrets),
            { entrypoint: LOADED_TOOL.python_code.entrypoint }
        );

        service.updatePythonCodeToolV2(LOADED_TOOL.id, payload).subscribe();

        const request = httpMock.expectOne('/api/python-code-tool/7/');
        expect(request.request.method).toBe('PUT');
        expect(request.request.body).toEqual({
            name: 'Fetch orders',
            description: 'Fetches the latest orders',
            variables: [{ name: 'limit', type: 'integer' }],
            use_storage: true,
            python_code: {
                code: 'def main():\n    return 1\n',
                entrypoint: 'main',
                libraries: ['requests'],
                global_kwargs: {},
                secret_ids: [4],
            },
        });
        for (const key of READ_ONLY_KEYS) {
            expect(request.request.body).not.toHaveProperty(key);
        }
        request.flush(LOADED_TOOL);
    });
});
