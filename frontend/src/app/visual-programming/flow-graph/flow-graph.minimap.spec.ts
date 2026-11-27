import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PermissionsService } from '../../services/auth/permissions.service';
import { API_URL } from '../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../services/config';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { FlowViewOverrideService } from '../services/flow-view-override.service';
import { NodeAuthorshipStore } from '../services/node-authorship.store';
import { createStartNode } from '../utils/load';
import { FlowGraphComponent } from './flow-graph.component';

/** The real template: whether the minimap is there is the template's own decision. */
describe('FlowGraphComponent minimap', () => {
    let fixture: ComponentFixture<FlowGraphComponent>;
    let http: HttpTestingController;

    beforeEach(() => {
        localStorage.clear();
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                { provide: PermissionsService, useValue: { can: () => true, meets: () => true } },
                { provide: Dialog, useValue: { open: vi.fn(), openDialogs: [] } },
                NodeAuthorshipStore,
            ],
        });
        http = TestBed.inject(HttpTestingController);
        TestBed.inject(FlowViewOverrideService).load(5);
        fixture = TestBed.createComponent(FlowGraphComponent);
        fixture.componentRef.setInput('flowState', { nodes: [createStartNode()], connections: [] });
    });

    afterEach(() => vi.unstubAllGlobals());

    function openFlowWith(settings: Record<string, unknown>): void {
        http.expectOne({ method: 'GET', url: '/api/graphs/5/my-view-settings/' }).flush({ settings });
        fixture.detectChanges();
    }

    it('shows the minimap by default', () => {
        openFlowWith({});

        expect(fixture.nativeElement.querySelector('f-minimap')).not.toBeNull();
    });

    it('hides the minimap when show_minimap is false', () => {
        openFlowWith({ show_minimap: false });

        expect(fixture.nativeElement.querySelector('f-minimap')).toBeNull();
    });
});
