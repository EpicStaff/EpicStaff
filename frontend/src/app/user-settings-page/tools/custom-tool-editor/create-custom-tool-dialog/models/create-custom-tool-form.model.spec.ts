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
        venv_id: 12,
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
                venvId: LOADED_TOOL.python_code.venv_id ?? null,
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
                venv_id: 12,
                global_kwargs: {},
                secret_ids: [4],
            },
        });
        for (const key of READ_ONLY_KEYS) {
            expect(request.request.body).not.toHaveProperty(key);
        }
        request.flush(LOADED_TOOL);
    });

    it('sends the chosen venv when a new tool is created', () => {
        // Create and update build their body through the same toCreatePayload, so
        // nothing but this pins the venv to the create request as well.
        const payload = toCreatePayload(
            {
                name: '  Fetch orders  ',
                description: 'Fetches the latest orders',
                pythonCode: 'def main():\n    return 1\n',
                variablesJson: '[]',
                venvId: 12,
                useStorage: false,
            },
            [4]
        );

        service.createPythonCodeToolV2(payload).subscribe();

        const request = httpMock.expectOne('/api/python-code-tool/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({
            name: 'Fetch orders',
            description: 'Fetches the latest orders',
            variables: [],
            use_storage: false,
            python_code: {
                code: 'def main():\n    return 1\n',
                entrypoint: 'main',
                venv_id: 12,
                global_kwargs: {},
                secret_ids: [4],
            },
        });
        request.flush(LOADED_TOOL);
    });

    it('clears the venv when the tool is saved without one', () => {
        // `null` has to travel: the backend applies the keys it is given, so an
        // omitted venv_id would keep the venv the user just removed.
        const payload = toCreatePayload(
            {
                name: LOADED_TOOL.name,
                description: LOADED_TOOL.description,
                pythonCode: LOADED_TOOL.python_code.code,
                variablesJson: JSON.stringify(LOADED_TOOL.variables),
                venvId: null,
                useStorage: false,
            },
            [],
            { entrypoint: 'main' }
        );

        service.updatePythonCodeToolV2(LOADED_TOOL.id, payload).subscribe();

        const request = httpMock.expectOne('/api/python-code-tool/7/');
        expect(request.request.body.python_code).toHaveProperty('venv_id', null);
        request.flush(LOADED_TOOL);
    });

    it('sends the execution timeout with the code when the dialog has one', () => {
        const payload = toCreatePayload(
            {
                name: 'Fetch orders',
                description: 'Fetches the latest orders',
                pythonCode: 'def main():\n    return 1\n',
                variablesJson: '[]',
                venvId: null,
                useStorage: false,
                executionTimeout: 300,
            },
            []
        );

        expect(payload.python_code.execution_timeout).toBe(300);
    });

    it('sends no execution timeout when the dialog has none, so the backend applies its own', () => {
        const payload = toCreatePayload(
            {
                name: 'Fetch orders',
                description: 'Fetches the latest orders',
                pythonCode: 'def main():\n    return 1\n',
                variablesJson: '[]',
                venvId: null,
                useStorage: false,
                executionTimeout: undefined,
            },
            []
        );

        expect(payload.python_code).not.toHaveProperty('execution_timeout');
    });
});
