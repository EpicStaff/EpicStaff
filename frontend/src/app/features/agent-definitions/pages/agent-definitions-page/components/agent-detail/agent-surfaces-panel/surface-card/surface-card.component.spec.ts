import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService, ConfirmationDialogService } from '@shared/components';

import { PermissionsService } from '../../../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../../../services/notifications';
import { StorageApiService } from '../../../../../../../files/services/storage-api.service';
import { StorageDragService } from '../../../../../../../files/services/storage-drag.service';
import { CollectionsStorageService } from '../../../../../../../knowledge-sources/services/collections-storage.service';
import { Surface } from '../../../../../../models/surface.model';
import { SurfaceCatalogsStore } from '../../../../../../services/surface-catalogs-store.service';
import { SurfaceCardComponent } from './surface-card.component';

const SURFACE: Surface = {
    id: 5,
    org: 1,
    name: 'Surface_1',
    description: '',
    instructions: '',
    owner_agent: null,
    allow_creation: false,
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

interface RenderOptions {
    canWrite: boolean;
    isShared?: boolean;
    showMeta?: boolean;
    readOnly?: boolean;
}

function render(options: RenderOptions): {
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
    fixture.componentRef.setInput('surface', SURFACE);
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
        const { fixture, overlay } = render({ canWrite: true, isShared: true, showMeta: true });

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Duplicate', 'View Details']);
        expect(overlay.querySelector('.surface-card__places')).toBeNull();
    });

    it('follows the agent-specific actions on a surface owned by an agent', () => {
        const { fixture, overlay } = render({ canWrite: true });

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Duplicate', 'Make Shared', 'View Details']);
        expect(overlay.querySelector('.surface-card__places')).toBeNull();
    });

    it('sits between the actions and the place checkboxes on a shared surface shown under an agent', () => {
        const { fixture, overlay } = render({ canWrite: true, isShared: true, readOnly: true });

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Make Agent-Specific Copy', 'View Details']);
        const places = overlay.querySelector('.surface-card__places');
        expect(places).not.toBeNull();
        expect(viewDetailsItem(overlay)!.compareDocumentPosition(places!) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
            Node.DOCUMENT_POSITION_FOLLOWING
        );
    });

    it('is offered to a user who can only read surfaces, as the only item', () => {
        const { fixture, host, overlay } = render({ canWrite: false, isShared: true, showMeta: true, readOnly: true });

        expect(moreButton(host)).not.toBeNull();
        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['View Details']);
    });

    it('opens "Surface Details" for the surface, to close back to the trigger, and closes the menu', () => {
        const { fixture, host, overlay } = render({ canWrite: true, isShared: true, showMeta: true });
        const open = vi
            .spyOn(TestBed.inject(AuthorshipDetailsDialogService), 'open')
            .mockReturnValue({} as ReturnType<AuthorshipDetailsDialogService['open']>);

        openMenu(fixture);
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        expect(open).toHaveBeenCalledWith('Surface Details', SURFACE, moreButton(host));
        expect(viewDetailsItem(overlay)).toBeNull();
    });

    it('returns focus to the trigger once the details dialog closes, not to the destroyed menu item', () => {
        const { fixture, host, overlay } = render({ canWrite: true, isShared: true, showMeta: true });
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
