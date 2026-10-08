import { Dialog } from '@angular/cdk/dialog';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ConfirmationDialogService } from '@shared/components';
import { ResourceCode } from '@shared/models';
import { EMPTY } from 'rxjs';

import { PermissionsService } from '../../../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../../../services/notifications';
import { StorageApiService } from '../../../../../../../files/services/storage-api.service';
import { StorageDragService } from '../../../../../../../files/services/storage-drag.service';
import { CollectionsStorageService } from '../../../../../../../knowledge-sources/services/collections-storage.service';
import { Surface } from '../../../../../../models/surface.model';
import { SurfaceCatalogsStore } from '../../../../../../services/surface-catalogs-store.service';
import { SurfaceCardComponent } from './surface-card.component';
import { SurfaceKnowledgeAdvancedComponent } from './surface-knowledge-advanced/surface-knowledge-advanced.component';

const SURFACE: Surface = {
    id: 5,
    organization: 1,
    name: 'Research',
    instructions: '',
    owner_agent: null,
    python_tools: [{ python_tool: 1, mode: 'deny' }],
    mcp_tools: [
        { mcp_tool: 2, mode: 'deny' },
        { mcp_tool: 3, mode: 'allow' },
    ],
    storage_items: [],
    knowledge: [],
    created_at: '',
    updated_at: '',
};

const CATALOGS: Partial<SurfaceCatalogsStore> = {
    loadPythonTools: () => EMPTY,
    loadMcpTools: () => EMPTY,
    loadCollections: () => EMPTY,
    loadStorageTree: () => EMPTY,
};

@Component({
    selector: 'app-surface-knowledge-advanced',
    template: '',
    providers: [{ provide: SurfaceKnowledgeAdvancedComponent, useExisting: KnowledgeAdvancedStubComponent }],
})
class KnowledgeAdvancedStubComponent {
    readonly invalidConfig = signal(false);
    readonly flush = vi.fn();
}

function render(template = '', toast: Partial<ToastService> = {}): ComponentFixture<SurfaceCardComponent> {
    TestBed.configureTestingModule({
        providers: [
            { provide: SurfaceCatalogsStore, useValue: CATALOGS },
            { provide: StorageApiService, useValue: {} },
            { provide: StorageDragService, useValue: { isDragging: signal(false) } },
            { provide: ToastService, useValue: toast },
            { provide: CollectionsStorageService, useValue: {} },
            { provide: Dialog, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: PermissionsService, useValue: { can: () => true } },
        ],
    });
    TestBed.overrideComponent(SurfaceCardComponent, {
        set: { template, imports: template ? [KnowledgeAdvancedStubComponent] : [] },
    });
    const fixture = TestBed.createComponent(SurfaceCardComponent);
    fixture.componentRef.setInput('surface', SURFACE);
    fixture.detectChanges();
    return fixture;
}

describe('SurfaceCardComponent tool modes', () => {
    it('sends each stored tool mode back unchanged instead of rewriting deny to allow', () => {
        const request = render().componentInstance.buildCreateRequest('Research copy');

        expect(request.python_tools).toEqual([{ python_tool: 1, mode: 'deny' }]);
        expect(request.mcp_tools).toEqual([
            { mcp_tool: 2, mode: 'deny' },
            { mcp_tool: 3, mode: 'allow' },
        ]);
    });

    it('adds a newly selected tool as allow', () => {
        const card = render().componentInstance;
        card.selectedToolKeys.update((keys) => new Set([...keys, 'mcp:9']));

        expect(card.buildCreateRequest('Research copy').mcp_tools).toContainEqual({ mcp_tool: 9, mode: 'allow' });
    });
});

describe('SurfaceCardComponent invalid knowledge settings', () => {
    function renderWithInvalidKnowledge(): {
        card: SurfaceCardComponent;
        advanced: KnowledgeAdvancedStubComponent;
        warning: ReturnType<typeof vi.fn>;
    } {
        const warning = vi.fn();
        const fixture = render('<app-surface-knowledge-advanced />', { warning });
        const advanced: KnowledgeAdvancedStubComponent = fixture.debugElement.query(
            By.directive(KnowledgeAdvancedStubComponent)
        ).componentInstance;
        const card = fixture.componentInstance;
        card.collectionAdvancedOpen.set(true);
        card.activeTab.set(ResourceCode.KnowledgeSources);
        card.expanded.set(true);
        advanced.invalidConfig.set(true);
        return { card, advanced, warning };
    }

    it('keeps the advanced settings open and warns instead of dropping the invalid edit', () => {
        const { card, advanced, warning } = renderWithInvalidKnowledge();

        card.toggleCollectionAdvanced();

        expect(advanced.flush).toHaveBeenCalled();
        expect(card.collectionAdvancedOpen()).toBe(true);
        expect(card.knowledgeInvalid()).toBe(true);
        expect(warning).toHaveBeenCalledTimes(1);
    });

    it('refuses to leave the knowledge tab or collapse the card while the settings are invalid', () => {
        const { card } = renderWithInvalidKnowledge();

        card.selectTab(ResourceCode.Tools);
        card.toggleExpand();

        expect(card.activeTab()).toBe(ResourceCode.KnowledgeSources);
        expect(card.expanded()).toBe(true);
    });

    it('collapses normally once the settings are valid', () => {
        const { card, advanced, warning } = renderWithInvalidKnowledge();
        advanced.invalidConfig.set(false);

        card.toggleCollectionAdvanced();

        expect(card.collectionAdvancedOpen()).toBe(false);
        expect(warning).not.toHaveBeenCalled();
    });
});
