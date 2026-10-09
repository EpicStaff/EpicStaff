import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { AuthorshipDetailsDialogService, ConfirmationDialogService } from '@shared/components';
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
    org: 1,
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
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
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

const DETAILS_SURFACE: Surface = {
    id: 5,
    org: 1,
    name: 'Surface_1',
    instructions: '',
    owner_agent: null,
    python_tools: [],
    mcp_tools: [],
    storage_items: [],
    knowledge: [],
    created_at: '2026-03-12T13:28:23Z',
    updated_at: '2026-03-13T09:00:00Z',
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    last_edited_by: { id: 2, display_name: 'Olena Petrenko', avatar_url: null },
    last_edited_at: '2026-03-13T09:00:00Z',
};

interface RenderMenuOptions {
    canWrite: boolean;
    isShared?: boolean;
    showMeta?: boolean;
    readOnly?: boolean;
}

function renderMenu(options: RenderMenuOptions): {
    fixture: ComponentFixture<SurfaceCardComponent>;
    host: HTMLElement;
    overlay: HTMLElement;
} {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PermissionsService,
                useValue: { can: () => options.canWrite, canAny: () => options.canWrite },
            },
            {
                provide: SurfaceCatalogsStore,
                useValue: {
                    pythonTools: signal([]),
                    mcpTools: signal([]),
                    collections: signal([]),
                    storageTree: signal([]),
                    storageFileMeta: signal(new Map()),
                },
            },
            { provide: StorageDragService, useValue: { isDragging: signal(false) } },
            { provide: StorageApiService, useValue: {} },
            { provide: CollectionsStorageService, useValue: {} },
            { provide: ToastService, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
        ],
    });
    const fixture = TestBed.createComponent(SurfaceCardComponent);
    fixture.componentRef.setInput('surface', DETAILS_SURFACE);
    fixture.componentRef.setInput('isShared', options.isShared ?? false);
    fixture.componentRef.setInput('showMeta', options.showMeta ?? false);
    fixture.componentRef.setInput('readOnly', options.readOnly ?? false);
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, host: fixture.nativeElement as HTMLElement, overlay };
}

function moreButton(host: HTMLElement): HTMLButtonElement | null {
    return host.querySelector<HTMLButtonElement>('[aria-label="More actions"]');
}

function openMenu(fixture: ComponentFixture<SurfaceCardComponent>): void {
    moreButton(fixture.nativeElement)!.click();
    fixture.detectChanges();
}

function menuItemLabels(overlay: HTMLElement): string[] {
    return Array.from(overlay.querySelectorAll('.surface-card__menu-item')).map(
        (item) => item.textContent?.trim() ?? ''
    );
}

function viewDetailsItem(overlay: HTMLElement): HTMLButtonElement | null {
    return (
        Array.from(overlay.querySelectorAll<HTMLButtonElement>('.surface-card__menu-item')).find(
            (item) => item.textContent?.trim() === 'View Details'
        ) ?? null
    );
}

describe('SurfaceCardComponent more menu "View Details"', () => {
    it('follows Duplicate on a shared surface opened from Shared Surfaces', () => {
        const { fixture, overlay } = renderMenu({ canWrite: true, isShared: true, showMeta: true });

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Duplicate', 'View Details']);
        expect(overlay.querySelector('.surface-card__places')).toBeNull();
    });

    it('follows the agent-specific actions on a surface owned by an agent', () => {
        const { fixture, overlay } = renderMenu({ canWrite: true });

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Duplicate', 'Make Shared', 'View Details']);
        expect(overlay.querySelector('.surface-card__places')).toBeNull();
    });

    it('sits between the actions and the place checkboxes on a shared surface shown under an agent', () => {
        const { fixture, overlay } = renderMenu({ canWrite: true, isShared: true, readOnly: true });

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Make Agent-Specific Copy', 'View Details']);
        const places = overlay.querySelector('.surface-card__places');
        expect(places).not.toBeNull();
        expect(viewDetailsItem(overlay)!.compareDocumentPosition(places!) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
            Node.DOCUMENT_POSITION_FOLLOWING
        );
    });

    it('is offered to a user who can only read surfaces, as the only item', () => {
        const { fixture, host, overlay } = renderMenu({
            canWrite: false,
            isShared: true,
            showMeta: true,
            readOnly: true,
        });

        expect(moreButton(host)).not.toBeNull();
        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['View Details']);
    });

    it('opens "Surface Details" for the surface, to close back to the trigger, and closes the menu', () => {
        const { fixture, host, overlay } = renderMenu({ canWrite: true, isShared: true, showMeta: true });
        const open = vi
            .spyOn(TestBed.inject(AuthorshipDetailsDialogService), 'open')
            .mockReturnValue({} as ReturnType<AuthorshipDetailsDialogService['open']>);

        openMenu(fixture);
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        expect(open).toHaveBeenCalledWith('Surface Details', DETAILS_SURFACE, moreButton(host));
        expect(viewDetailsItem(overlay)).toBeNull();
    });

    it('returns focus to the trigger once the details dialog closes, not to the destroyed menu item', () => {
        const { fixture, host, overlay } = renderMenu({ canWrite: true, isShared: true, showMeta: true });
        const dialog = TestBed.inject(Dialog);
        const trigger = moreButton(host)!;

        openMenu(fixture);
        viewDetailsItem(overlay)!.focus();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();
        expect(dialog.openDialogs).toHaveLength(1);

        dialog.openDialogs[0].close();
        fixture.detectChanges();

        expect(dialog.openDialogs).toHaveLength(0);
        expect(document.activeElement).toBe(trigger);
    });
});
