import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { ToastService } from '../../../services/notifications';
import { AgentDefinition } from '../models/agent-definition.model';
import { Surface } from '../models/surface.model';
import { AgentsPageStore } from './agents-page-store.service';
import { SurfaceCatalogsStore } from './surface-catalogs-store.service';

const REFUSAL_MESSAGE = "This agent runs with Files: Write, which you don't have. Contact an admin to change it.";
const REFUSAL_BODY = {
    status_code: 403,
    code: 'storage_grant_denied',
    message: REFUSAL_MESSAGE,
    missing_grants: ['write'],
};

describe('AgentsPageStore saves refused for missing Files permissions', () => {
    let store: AgentsPageStore;
    let httpMock: HttpTestingController;
    let toast: { error: ReturnType<typeof vi.fn>; success: ReturnType<typeof vi.fn>; info: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        toast = { error: vi.fn(), success: vi.fn(), info: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                AgentsPageStore,
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: ToastService, useValue: toast },
                { provide: SurfaceCatalogsStore, useValue: { reloadLoadedCatalogs: vi.fn() } },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        store = TestBed.inject(AgentsPageStore);
        httpMock = TestBed.inject(HttpTestingController);
        store.agents.set([
            {
                id: 1,
                name: 'Writer',
                instruction_list: [{ name: 'Main', content: 'old' }],
                default_surfaces: [],
            } as unknown as AgentDefinition,
        ]);
        store.surfaces.set([{ id: 9, name: 'Docs', owner_agent: 1 } as unknown as Surface]);
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    function refuse(url: string): void {
        httpMock.expectOne(url).flush(REFUSAL_BODY, { status: 403, statusText: 'Forbidden' });
    }

    it('toasts the server message when an instruction change is refused and restores the list', () => {
        store.updateInstructionList(1, [{ name: 'Main', content: 'new' }]);

        refuse('/api/agent-definitions/1/');

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(REFUSAL_MESSAGE);
        expect(store.agents()[0].instruction_list).toEqual([{ name: 'Main', content: 'old' }]);
    });

    it('toasts the server message when a default-surfaces change is refused', () => {
        store.makeSurfaceShared(9);

        refuse('/api/agent-definitions/1/');

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(REFUSAL_MESSAGE);
    });

    it('toasts the server message when a surface edit is refused', () => {
        vi.useFakeTimers();

        store.updateSurface(9, { instructions: 'changed' });
        vi.advanceTimersByTime(500);
        refuse('/api/surfaces/9/');

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(REFUSAL_MESSAGE);
    });
});
