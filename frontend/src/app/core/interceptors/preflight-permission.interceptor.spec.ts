import { HttpClient, HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { firstValueFrom } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ConfigService } from '../../services/config';
import { withCrossOrgPermission, withPermission } from '../http/permission-context';
import { preflightPermissionInterceptor } from './preflight-permission.interceptor';

const GATED_URL = '/api/agents/';
const ORG_PERMISSIONS_URL = '/api/permissions/me/orgs/';
const FALLBACK_BODY = { results: [] };
const SERVER_BODY = { results: [{ id: 1 }] };

function grants(actions: ActionCode[]): Record<ResourceCode, ActionCode[]> {
    return { [ResourceCode.Agents]: actions } as Record<ResourceCode, ActionCode[]>;
}

interface ScopeCase {
    name: string;
    context: () => HttpContext;
    /** Loads a permission set for the scope that grants `actions` on agents. */
    load: (permissions: PermissionsService, actions: ActionCode[], httpMock: HttpTestingController) => void;
}

const scopeCases: ScopeCase[] = [
    {
        name: 'withPermission (active org)',
        context: () => withPermission(ResourceCode.Agents, ActionCode.Read, FALLBACK_BODY),
        load: (permissions, actions) =>
            permissions.setActivePermissions({
                org_id: 1,
                is_superadmin: false,
                role: { id: 1, name: 'Custom' },
                permissions: grants(actions),
            }),
    },
    {
        name: 'withCrossOrgPermission (any org)',
        context: () => withCrossOrgPermission(ResourceCode.Agents, ActionCode.Read, FALLBACK_BODY),
        load: (permissions, actions, httpMock) => {
            permissions.loadOrgPermissions().subscribe();
            httpMock.expectOne(ORG_PERMISSIONS_URL).flush({
                is_superadmin: false,
                orgs: [{ org: { id: 1, name: 'Org' }, role: { id: 1, name: 'Custom' }, permissions: grants(actions) }],
            });
        },
    },
];

describe('preflightPermissionInterceptor', () => {
    let httpClient: HttpClient;
    let httpMock: HttpTestingController;
    let permissions: PermissionsService;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([preflightPermissionInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });

        httpClient = TestBed.inject(HttpClient);
        httpMock = TestBed.inject(HttpTestingController);
        permissions = TestBed.inject(PermissionsService);
    });

    afterEach(() => httpMock.verify());

    async function expectSentToNetwork(context: HttpContext): Promise<void> {
        const response = firstValueFrom(httpClient.get(GATED_URL, { context }));
        httpMock.expectOne(GATED_URL).flush(SERVER_BODY);
        expect(await response).toEqual(SERVER_BODY);
    }

    async function expectFallbackWithoutRequest(context: HttpContext): Promise<void> {
        const body = await firstValueFrom(httpClient.get(GATED_URL, { context }));
        httpMock.expectNone(GATED_URL);
        expect(body).toEqual(FALLBACK_BODY);
    }

    describe.each(scopeCases)('$name', (scope) => {
        it('sends the request when the permission set was never loaded', async () => {
            await expectSentToNetwork(scope.context());
        });

        it('sends the request when the permission set was cleared', async () => {
            scope.load(permissions, [], httpMock);
            permissions.clear();
            await expectSentToNetwork(scope.context());
        });

        it('returns the fallback without a request when the loaded set lacks the permission', async () => {
            scope.load(permissions, [], httpMock);
            await expectFallbackWithoutRequest(scope.context());
        });

        it('sends the request when the loaded set grants the permission', async () => {
            scope.load(permissions, [ActionCode.Read], httpMock);
            await expectSentToNetwork(scope.context());
        });
    });

    it('returns the fallback for a zero-membership user, whose active permissions are loaded as null', async () => {
        permissions.setActivePermissions(null);
        await expectFallbackWithoutRequest(withPermission(ResourceCode.Agents, ActionCode.Read, FALLBACK_BODY));
    });
});
