import { ESCAPE } from '@angular/cdk/keycodes';
import { OverlayContainer } from '@angular/cdk/overlay';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode } from '@shared/models';
import { Observable, of, Subject, tap, throwError } from 'rxjs';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../../services/notifications';
import { COLLECTION_DESCRIPTION_MAX_LENGTH } from '../../../../../constants/constants';
import { CollectionStatus, CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { COLLECTION_AUTOSAVE_DEBOUNCE_MS } from '../../../../../services/collection-field-save.service';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { CollectionBasicsComponent } from './collection-basics.component';

const COLLECTION: CreateCollectionDtoResponse = {
    collection_id: 7,
    collection_name: 'CoreStack',
    description: 'Release notes',
    status: CollectionStatus.COMPLETED,
    document_count: 0,
    rag_configurations: [],
    created_at: '2026-03-12T13:28:23Z',
    updated_at: '2026-03-12T13:28:23Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

interface Rendered {
    fixture: ComponentFixture<CollectionBasicsComponent>;
    host: HTMLElement;
    overlay: HTMLElement;
    update: ReturnType<typeof vi.fn>;
    toast: { success: ReturnType<typeof vi.fn>; error: ReturnType<typeof vi.fn> };
    viewDetails: HTMLElement[];
    deletes: number;
}

function render(
    allowedActions: ActionCode[],
    respond: (body: Partial<CreateCollectionDtoResponse>) => Observable<CreateCollectionDtoResponse> = (body) =>
        of({ ...COLLECTION, ...body })
): Rendered {
    // Stands in for the storage cache: a response updates the cached collection, as the real storage does.
    const cache = signal<CreateCollectionDtoResponse[]>([COLLECTION, { ...COLLECTION, collection_id: 8 }]);
    const update = vi.fn((id: number, body: Partial<CreateCollectionDtoResponse>) =>
        respond(body).pipe(
            tap(() =>
                cache.update((collections) =>
                    collections.map((collection) =>
                        collection.collection_id === id ? { ...collection, ...body } : collection
                    )
                )
            )
        )
    );
    const toast = { success: vi.fn(), error: vi.fn() };
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PermissionsService,
                useValue: { can: (_: unknown, action: ActionCode) => allowedActions.includes(action) },
            },
            { provide: CollectionsStorageService, useValue: { updateCollectionById: update, fullCollections: cache } },
            { provide: ToastService, useValue: toast },
        ],
    });
    const fixture = TestBed.createComponent(CollectionBasicsComponent);
    fixture.componentRef.setInput('collection', COLLECTION);
    const rendered: Rendered = {
        fixture,
        host: fixture.nativeElement as HTMLElement,
        overlay: TestBed.inject(OverlayContainer).getContainerElement(),
        update,
        toast,
        viewDetails: [],
        deletes: 0,
    };
    fixture.componentInstance.viewDetailsClick.subscribe((trigger) => rendered.viewDetails.push(trigger));
    fixture.componentInstance.deleteClick.subscribe(() => rendered.deletes++);
    fixture.detectChanges();
    return rendered;
}

function moreButton(host: HTMLElement): HTMLButtonElement {
    return host.querySelector<HTMLButtonElement>('[aria-label="More actions"]')!;
}

function menuItems(overlay: HTMLElement): HTMLButtonElement[] {
    return Array.from(overlay.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
}

function openMenu({ fixture, host, overlay }: Rendered): HTMLButtonElement[] {
    moreButton(host).click();
    fixture.detectChanges();
    return menuItems(overlay);
}

function guidance(host: HTMLElement): HTMLTextAreaElement | null {
    return host.querySelector<HTMLTextAreaElement>('textarea#collection-guidance');
}

function nameInput(host: HTMLElement): HTMLInputElement {
    return host.querySelector<HTMLInputElement>('input#collection-name')!;
}

function click(fixture: ComponentFixture<CollectionBasicsComponent>, selector: string): void {
    (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>(selector)!.click();
    fixture.detectChanges();
}

const EDIT = '[aria-label="Edit guidance"]';
const SAVE = 'button[aria-label="Save guidance"]';
const CANCEL = 'button[aria-label="Cancel"]';

function type(
    fixture: ComponentFixture<CollectionBasicsComponent>,
    field: HTMLInputElement | HTMLTextAreaElement,
    value: string
): void {
    field.value = value;
    field.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

/** CDK menus read the legacy `keyCode`, which a synthetic `KeyboardEvent` cannot be constructed with. */
function pressEscape(target: HTMLElement): void {
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    Object.defineProperty(event, 'keyCode', { get: () => ESCAPE });
    target.dispatchEvent(event);
}

const EDITOR = [ActionCode.Read, ActionCode.Update, ActionCode.Delete];
const VIEWER = [ActionCode.Read];

describe('CollectionBasicsComponent ⋮ menu', () => {
    it('offers "View Details" and "Delete" to a user who may delete, with the trigger marked active', () => {
        const rendered = render(EDITOR);

        const items = openMenu(rendered);

        expect(items.map((item) => item.textContent?.trim())).toEqual(['View Details', 'Delete']);
        expect(moreButton(rendered.host).classList).toContain('basics__menu-trigger--active');
    });

    it('offers only "View Details" to a user who may not delete', () => {
        const items = openMenu(render(VIEWER));

        expect(items.map((item) => item.textContent?.trim())).toEqual(['View Details']);
    });

    it('emits the ⋮ button with "View Details", for the dialog to restore focus to, and closes the menu', () => {
        const rendered = render(VIEWER);
        const [viewDetails] = openMenu(rendered);

        viewDetails.click();
        rendered.fixture.detectChanges();

        expect(rendered.viewDetails).toEqual([moreButton(rendered.host)]);
        expect(menuItems(rendered.overlay)).toEqual([]);
        expect(moreButton(rendered.host).classList).not.toContain('basics__menu-trigger--active');
    });

    it('emits deleteClick with "Delete"', () => {
        const rendered = render(EDITOR);

        openMenu(rendered)[1].click();
        rendered.fixture.detectChanges();

        expect(rendered.deletes).toBe(1);
        expect(rendered.viewDetails).toEqual([]);
    });

    // The page is not inside a dialog, so CdkMenu's own Escape handling is enough (no interceptor).
    it('closes on Escape and returns focus to the ⋮ button', () => {
        const rendered = render(EDITOR);
        const [viewDetails] = openMenu(rendered);

        pressEscape(viewDetails);
        rendered.fixture.detectChanges();

        expect(menuItems(rendered.overlay)).toEqual([]);
        expect(document.activeElement).toBe(moreButton(rendered.host));
    });
});

describe('CollectionBasicsComponent guidance for agents', () => {
    it('shows the stored guidance as text with an Edit button', () => {
        const { host } = render(EDITOR);

        expect(guidance(host)).toBeNull();
        expect(host.querySelector('.basics__readonly--guidance')?.textContent?.trim()).toBe('Release notes');
        expect(host.querySelector(EDIT)).not.toBeNull();
    });

    it('edits in a textarea and saves the trimmed text only on Save', () => {
        const { fixture, host, update, toast } = render(EDITOR);

        click(fixture, EDIT);
        expect(guidance(host)!.value).toBe('Release notes');

        type(fixture, guidance(host)!, '  Release notes for agents  ');
        expect(update).not.toHaveBeenCalled();
        click(fixture, SAVE);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'Release notes for agents' });
        expect(toast.success).toHaveBeenCalledWith('Collection Updated');
        expect(guidance(host)).toBeNull();
    });

    it('discards the edit on Cancel', () => {
        const { fixture, host, update } = render(EDITOR);

        click(fixture, EDIT);
        type(fixture, guidance(host)!, 'Never mind');
        click(fixture, CANCEL);

        expect(update).not.toHaveBeenCalled();
        expect(guidance(host)).toBeNull();
        expect(host.querySelector('.basics__readonly--guidance')?.textContent?.trim()).toBe('Release notes');
    });

    it('does not save unchanged guidance', () => {
        const { fixture, host, update } = render(EDITOR);

        click(fixture, EDIT);
        type(fixture, guidance(host)!, 'Release notes ');
        click(fixture, SAVE);

        expect(update).not.toHaveBeenCalled();
    });

    it('allows guidance up to the backend limit and blocks Save beyond it', () => {
        const { fixture, host, update } = render(EDITOR);
        const saveButton = (): HTMLButtonElement => host.querySelector<HTMLButtonElement>(SAVE)!;

        click(fixture, EDIT);
        type(fixture, guidance(host)!, 'x'.repeat(COLLECTION_DESCRIPTION_MAX_LENGTH + 1));
        expect(COLLECTION_DESCRIPTION_MAX_LENGTH).toBe(2000);
        expect(saveButton().disabled).toBe(true);

        type(fixture, guidance(host)!, 'x'.repeat(COLLECTION_DESCRIPTION_MAX_LENGTH));
        click(fixture, SAVE);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, {
            description: 'x'.repeat(COLLECTION_DESCRIPTION_MAX_LENGTH),
        });
    });

    it('reopens the editor with the draft intact when the save fails', () => {
        const { fixture, host, toast } = render(EDITOR, () => throwError(() => new Error('500')));

        click(fixture, EDIT);
        type(fixture, guidance(host)!, 'Draft guidance');
        click(fixture, SAVE);

        expect(toast.error).toHaveBeenCalledWith('Collection Update failed');
        expect(guidance(host)!.value).toBe('Draft guidance');
    });

    it('closes an open edit when another collection is selected, as the guidance panel did', () => {
        const { fixture, host, update } = render(EDITOR);

        click(fixture, EDIT);
        type(fixture, guidance(host)!, 'Unsaved');
        fixture.componentRef.setInput('collection', { ...COLLECTION, collection_id: 8, description: 'Other' });
        fixture.detectChanges();

        expect(guidance(host)).toBeNull();
        expect(update).not.toHaveBeenCalled();
        expect(host.querySelector('.basics__readonly--guidance')?.textContent?.trim()).toBe('Other');
    });

    it('finishes a save already in flight after the component is destroyed', () => {
        const response = new Subject<CreateCollectionDtoResponse>();
        const { fixture, host, toast } = render(EDITOR, () => response);

        click(fixture, EDIT);
        type(fixture, guidance(host)!, 'In flight');
        click(fixture, SAVE);
        fixture.destroy();
        response.next({ ...COLLECTION, description: 'In flight' });
        response.complete();

        expect(toast.success).toHaveBeenCalledOnce();
    });

    it('is read-only text without an Edit button for a user who may not update the collection', () => {
        const { host } = render(VIEWER);

        expect(host.querySelector(EDIT)).toBeNull();
        expect(host.querySelector('input#collection-name')).toBeNull();
        expect(host.querySelector('.basics__readonly--guidance')?.textContent?.trim()).toBe('Release notes');
    });

    it('says so when there is no guidance', () => {
        const { fixture, host } = render(VIEWER);

        fixture.componentRef.setInput('collection', { ...COLLECTION, description: null });
        fixture.detectChanges();

        expect(host.querySelector('.basics__readonly--empty')?.textContent?.trim()).toBe('No guidance provided.');
    });
});

describe('CollectionBasicsComponent collection name autosave', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('saves the trimmed name once typing pauses', () => {
        const { fixture, host, update, toast } = render(EDITOR);

        type(fixture, nameInput(host), 'CoreStack');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS - 1);
        type(fixture, nameInput(host), 'CoreStack v2 ');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS - 1);
        expect(update).not.toHaveBeenCalled();

        vi.advanceTimersByTime(1);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { collection_name: 'CoreStack v2' });
        expect(toast.success).toHaveBeenCalledOnce();
    });

    it('does not save an empty name', () => {
        const { fixture, host, update } = render(EDITOR);

        type(fixture, nameInput(host), '   ');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).not.toHaveBeenCalled();
    });

    it('does not save a name that matches the stored one', () => {
        const { fixture, host, update } = render(EDITOR);

        type(fixture, nameInput(host), 'CoreStack ');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).not.toHaveBeenCalled();
    });

    it('keeps the unsaved name when the save fails', () => {
        const { fixture, host, toast } = render(EDITOR, () => throwError(() => new Error('500')));

        type(fixture, nameInput(host), 'Draft name');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);
        fixture.componentRef.setInput('collection', { ...COLLECTION });
        fixture.detectChanges();

        expect(toast.error).toHaveBeenCalledWith('Collection Update failed');
        expect(nameInput(host).value).toBe('Draft name');
    });

    it('saves to the edited collection right away when another is selected mid-debounce', () => {
        const { fixture, host, update } = render(EDITOR);

        type(fixture, nameInput(host), 'For collection 7');
        fixture.componentRef.setInput('collection', { ...COLLECTION, collection_id: 8, collection_name: 'Other' });
        fixture.detectChanges();

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { collection_name: 'For collection 7' });
        expect(nameInput(host).value).toBe('Other');

        type(fixture, nameInput(host), 'For collection 8');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);

        expect(update).toHaveBeenLastCalledWith(8, { collection_name: 'For collection 8' });
        expect(update).toHaveBeenCalledTimes(2);
    });

    it('saves a name still waiting out its debounce when the component is destroyed', () => {
        const { fixture, host, update } = render(EDITOR);

        type(fixture, nameInput(host), 'Typed just before leaving');
        fixture.destroy();

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { collection_name: 'Typed just before leaving' });
    });

    it('finishes a save already in flight after the component is destroyed', () => {
        const response = new Subject<CreateCollectionDtoResponse>();
        const { fixture, host, update, toast } = render(EDITOR, () => response);

        type(fixture, nameInput(host), 'In flight');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);
        fixture.destroy();
        response.next({ ...COLLECTION, collection_name: 'In flight' });
        response.complete();

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { collection_name: 'In flight' });
        expect(toast.success).toHaveBeenCalledOnce();
    });

    it('still saves a name equal to the stored one while a different name is in flight', () => {
        const responses: Subject<CreateCollectionDtoResponse>[] = [];
        const { fixture, host, update } = render(EDITOR, () => {
            const response = new Subject<CreateCollectionDtoResponse>();
            responses.push(response);
            return response;
        });

        type(fixture, nameInput(host), 'CoreStack v2');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);
        type(fixture, nameInput(host), 'CoreStack');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);
        responses[0].next({ ...COLLECTION, collection_name: 'CoreStack v2' });
        responses[0].complete();

        expect(update.mock.calls.map(([, body]) => body)).toEqual([
            { collection_name: 'CoreStack v2' },
            { collection_name: 'CoreStack' },
        ]);
    });

    it('keeps a name typed while a save is in flight instead of resetting it to the saved value', () => {
        const response = new Subject<CreateCollectionDtoResponse>();
        const { fixture, host } = render(EDITOR, () => response);

        type(fixture, nameInput(host), 'First');
        vi.advanceTimersByTime(COLLECTION_AUTOSAVE_DEBOUNCE_MS);
        type(fixture, nameInput(host), 'First and more');
        response.next({ ...COLLECTION, collection_name: 'First' });
        response.complete();
        fixture.componentRef.setInput('collection', { ...COLLECTION, collection_name: 'First' });
        fixture.detectChanges();

        expect(nameInput(host).value).toBe('First and more');
    });

    it('follows a name changed elsewhere while the field is not being edited', () => {
        const { fixture, host } = render(EDITOR);

        fixture.componentRef.setInput('collection', { ...COLLECTION, collection_name: 'Renamed in wizard' });
        fixture.detectChanges();

        expect(nameInput(host).value).toBe('Renamed in wizard');
    });
});
