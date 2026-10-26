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

function type(
    fixture: ComponentFixture<CollectionBasicsComponent>,
    field: HTMLInputElement | HTMLTextAreaElement,
    value: string
): void {
    field.value = value;
    field.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

function blur(fixture: ComponentFixture<CollectionBasicsComponent>, field: HTMLTextAreaElement): void {
    field.dispatchEvent(new Event('blur'));
    fixture.detectChanges();
}

/** CDK menus read the legacy `keyCode`, which a synthetic `KeyboardEvent` cannot be constructed with. */
function pressEscape(target: HTMLElement): void {
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    Object.defineProperty(event, 'keyCode', { get: () => ESCAPE });
    target.dispatchEvent(event);
}

/** jsdom has no ResizeObserver; this one reports a width only when a test says the field was resized. */
class FakeResizeObserver {
    static instances: FakeResizeObserver[] = [];
    private readonly observed = new Set<Element>();

    constructor(private readonly callback: ResizeObserverCallback) {
        FakeResizeObserver.instances.push(this);
    }

    static resize(target: Element, width: number): void {
        for (const instance of FakeResizeObserver.instances) {
            if (!instance.observed.has(target)) continue;
            const entry = { target, contentRect: { width } } as unknown as ResizeObserverEntry;
            instance.callback([entry], instance as unknown as ResizeObserver);
        }
    }

    observe(target: Element): void {
        this.observed.add(target);
    }

    unobserve(target: Element): void {
        this.observed.delete(target);
    }

    disconnect(): void {
        this.observed.clear();
    }
}

beforeEach(() => {
    FakeResizeObserver.instances = [];
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
});
afterEach(() => vi.unstubAllGlobals());

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

describe('CollectionBasicsComponent guidance for agents autosave', () => {
    it('saves the trimmed guidance when the field loses focus, not while typing', () => {
        const { fixture, host, update, toast } = render(EDITOR);
        expect(guidance(host)!.value).toBe('Release notes');

        type(fixture, guidance(host)!, '  Release notes for agents  ');
        expect(update).not.toHaveBeenCalled();
        blur(fixture, guidance(host)!);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'Release notes for agents' });
        expect(toast.success).toHaveBeenCalledWith('Collection Updated');
    });

    it('does not save guidance that was not edited or matches the stored one', () => {
        const { fixture, host, update } = render(EDITOR);

        blur(fixture, guidance(host)!);
        type(fixture, guidance(host)!, 'Release notes ');
        blur(fixture, guidance(host)!);

        expect(update).not.toHaveBeenCalled();
    });

    it('saves cleared guidance, which unlike the name may be empty', () => {
        const { fixture, host, update } = render(EDITOR);

        type(fixture, guidance(host)!, '   ');
        blur(fixture, guidance(host)!);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: '' });
    });

    it('saves guidance up to the backend limit and keeps longer guidance unsaved with an error', () => {
        const { fixture, host, update } = render(EDITOR);
        expect(COLLECTION_DESCRIPTION_MAX_LENGTH).toBe(2000);

        type(fixture, guidance(host)!, 'x'.repeat(2001));
        blur(fixture, guidance(host)!);

        expect(update).not.toHaveBeenCalled();
        expect(host.querySelector('.validation-errors')?.textContent).toContain('Max length is 2000');

        type(fixture, guidance(host)!, 'x'.repeat(2000));
        blur(fixture, guidance(host)!);

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'x'.repeat(2000) });
        expect(host.querySelector('.validation-errors')).toBeNull();
    });

    it('reverts to the stored guidance when the save fails', () => {
        const { fixture, host, toast } = render(EDITOR, () => throwError(() => new Error('500')));

        type(fixture, guidance(host)!, 'Draft guidance');
        blur(fixture, guidance(host)!);

        expect(toast.error).toHaveBeenCalledWith('Collection Update failed');
        expect(guidance(host)!.value).toBe('Release notes');
    });

    it('sends nothing on a blur after a failed save', () => {
        const { fixture, host, update } = render(EDITOR, () => throwError(() => new Error('500')));

        type(fixture, guidance(host)!, 'Draft guidance');
        blur(fixture, guidance(host)!);
        blur(fixture, guidance(host)!);

        expect(update).toHaveBeenCalledOnce();
    });

    it('leaves the guidance being typed alone when a save for the previous collection fails', () => {
        const response = new Subject<CreateCollectionDtoResponse>();
        const { fixture, host } = render(EDITOR, () => response);

        type(fixture, guidance(host)!, 'For collection 7');
        fixture.componentRef.setInput('collection', { ...COLLECTION, collection_id: 8, description: 'Other' });
        fixture.detectChanges();
        type(fixture, guidance(host)!, 'For collection 8');
        response.error(new Error('500'));
        fixture.detectChanges();

        expect(guidance(host)!.value).toBe('For collection 8');
    });

    it('follows guidance changed elsewhere once its own save has succeeded', () => {
        const { fixture, host } = render(EDITOR);

        type(fixture, guidance(host)!, 'Saved here');
        blur(fixture, guidance(host)!);
        fixture.componentRef.setInput('collection', { ...COLLECTION, description: 'Edited in wizard' });
        fixture.detectChanges();

        expect(guidance(host)!.value).toBe('Edited in wizard');
    });

    it('keeps guidance typed after a rejected save and sends it on the next blur', () => {
        const response = new Subject<CreateCollectionDtoResponse>();
        const { fixture, host, update } = render(EDITOR, () => response);

        type(fixture, guidance(host)!, 'First');
        blur(fixture, guidance(host)!);
        type(fixture, guidance(host)!, 'First and more');
        response.error(new Error('500'));
        fixture.detectChanges();

        expect(guidance(host)!.value).toBe('First and more');

        blur(fixture, guidance(host)!);

        expect(update.mock.calls.map(([, body]) => body)).toEqual([
            { description: 'First' },
            { description: 'First and more' },
        ]);
    });

    it.each([
        [
            'another collection is selected',
            (fixture: ComponentFixture<CollectionBasicsComponent>): void => {
                fixture.componentRef.setInput('collection', { ...COLLECTION, collection_id: 8 });
                fixture.detectChanges();
            },
        ],
        [
            'the component is destroyed',
            (fixture: ComponentFixture<CollectionBasicsComponent>): void => fixture.destroy(),
        ],
    ])('sends blurred guidance once when %s before the save fails', (_, leave) => {
        const response = new Subject<CreateCollectionDtoResponse>();
        const { fixture, host, update, toast } = render(EDITOR, () => response);

        type(fixture, guidance(host)!, 'Sent on blur');
        blur(fixture, guidance(host)!);
        leave(fixture);
        response.error(new Error('500'));

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'Sent on blur' });
        expect(toast.error).toHaveBeenCalledOnce();
    });

    it('saves unsaved guidance to the edited collection when another is selected without a blur', () => {
        const { fixture, host, update } = render(EDITOR);

        type(fixture, guidance(host)!, 'For collection 7');
        fixture.componentRef.setInput('collection', { ...COLLECTION, collection_id: 8, description: 'Other' });
        fixture.detectChanges();

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'For collection 7' });
        expect(guidance(host)!.value).toBe('Other');
    });

    it('saves unsaved guidance when the component is destroyed without a blur', () => {
        const { fixture, host, update } = render(EDITOR);

        type(fixture, guidance(host)!, 'Typed just before leaving');
        fixture.destroy();

        expect(update).toHaveBeenCalledExactlyOnceWith(7, { description: 'Typed just before leaving' });
    });

    it('keeps guidance typed while a save is in flight and saves it on the next blur', () => {
        const response = new Subject<CreateCollectionDtoResponse>();
        const { fixture, host, update } = render(EDITOR, () => response);

        type(fixture, guidance(host)!, 'First');
        blur(fixture, guidance(host)!);
        type(fixture, guidance(host)!, 'First and more');
        response.next({ ...COLLECTION, description: 'First' });
        response.complete();
        fixture.componentRef.setInput('collection', { ...COLLECTION, description: 'First' });
        fixture.detectChanges();

        expect(guidance(host)!.value).toBe('First and more');

        blur(fixture, guidance(host)!);

        expect(update).toHaveBeenLastCalledWith(7, { description: 'First and more' });
    });

    it('still saves guidance equal to the stored one while a different guidance is in flight', () => {
        const responses: Subject<CreateCollectionDtoResponse>[] = [];
        const { fixture, host, update } = render(EDITOR, () => {
            const response = new Subject<CreateCollectionDtoResponse>();
            responses.push(response);
            return response;
        });

        type(fixture, guidance(host)!, 'Changed');
        blur(fixture, guidance(host)!);
        type(fixture, guidance(host)!, 'Release notes');
        blur(fixture, guidance(host)!);
        responses[0].next({ ...COLLECTION, description: 'Changed' });
        responses[0].complete();

        expect(update.mock.calls.map(([, body]) => body)).toEqual([
            { description: 'Changed' },
            { description: 'Release notes' },
        ]);
    });

    it('follows guidance changed elsewhere while the field is not being edited', () => {
        const { fixture, host } = render(EDITOR);

        fixture.componentRef.setInput('collection', { ...COLLECTION, description: 'Edited in wizard' });
        fixture.detectChanges();

        expect(guidance(host)!.value).toBe('Edited in wizard');
    });

    it('is read-only text for a user who may not update the collection', () => {
        const { host } = render(VIEWER);

        expect(guidance(host)).toBeNull();
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

// jsdom has no layout, so the textarea's measurements are faked: 20px per line of text plus 18px of padding as the
// scroll and client height, plus a 2px border as the offset height. Measuring at auto height drops the scroll
// position, as the browser does when the box is as tall as its text. That checks when the field is fitted, the
// border, the 400px cap and the kept scroll position, not the browser's measurement itself. `TestBed.tick()`
// stands in for the application tick that runs render hooks after an event in the app.
describe('CollectionBasicsComponent guidance field height', () => {
    const LONG_GUIDANCE = Array.from({ length: 30 }, (_, index) => `Line ${index + 1}`).join('\n');
    const FAKED = ['scrollHeight', 'clientHeight', 'offsetHeight', 'scrollTop'] as const;
    let linesPerTextLine = 1;
    let scrollTops = new WeakMap<HTMLTextAreaElement, number>();

    function textHeight(textarea: HTMLTextAreaElement): number {
        return textarea.value.split('\n').length * linesPerTextLine * 20 + 18;
    }

    beforeEach(() => {
        linesPerTextLine = 1;
        scrollTops = new WeakMap();
        const prototype = HTMLTextAreaElement.prototype;
        Object.defineProperty(prototype, 'scrollHeight', {
            configurable: true,
            get(this: HTMLTextAreaElement): number {
                if (this.style.height === 'auto') scrollTops.set(this, 0);
                return textHeight(this);
            },
        });
        Object.defineProperty(prototype, 'clientHeight', {
            configurable: true,
            get(this: HTMLTextAreaElement): number {
                return textHeight(this);
            },
        });
        Object.defineProperty(prototype, 'offsetHeight', {
            configurable: true,
            get(this: HTMLTextAreaElement): number {
                return textHeight(this) + 2;
            },
        });
        Object.defineProperty(prototype, 'scrollTop', {
            configurable: true,
            get(this: HTMLTextAreaElement): number {
                return scrollTops.get(this) ?? 0;
            },
            set(this: HTMLTextAreaElement, value: number) {
                scrollTops.set(this, value);
            },
        });
    });
    afterEach(() => {
        for (const property of FAKED) {
            delete (HTMLTextAreaElement.prototype as Partial<Record<(typeof FAKED)[number], number>>)[property];
        }
    });

    it('fits the stored guidance when it is loaded and when another collection is selected', () => {
        const { fixture, host } = render(EDITOR);
        TestBed.tick();

        expect(guidance(host)!.style.height).toBe('40px');

        fixture.componentRef.setInput('collection', { ...COLLECTION, collection_id: 8, description: LONG_GUIDANCE });
        TestBed.tick();

        expect(guidance(host)!.style.height).toBe('400px');
        expect(guidance(host)!.style.overflowY).toBe('auto');
    });

    it('follows the typed text and fits the stored guidance again after a rejected save', () => {
        const { fixture, host } = render(EDITOR, () => throwError(() => new Error('500')));

        type(fixture, guidance(host)!, 'One\nTwo\nThree\nFour');
        expect(guidance(host)!.style.height).toBe('100px');
        expect(guidance(host)!.style.overflowY).toBe('hidden');

        blur(fixture, guidance(host)!);
        TestBed.tick();

        expect(guidance(host)!.value).toBe('Release notes');
        expect(guidance(host)!.style.height).toBe('40px');
    });

    it('keeps the scroll position of a field past the cap while typing', () => {
        const { fixture, host } = render(EDITOR);
        type(fixture, guidance(host)!, LONG_GUIDANCE);
        guidance(host)!.scrollTop = 120;

        type(fixture, guidance(host)!, `${LONG_GUIDANCE}!`);

        expect(guidance(host)!.style.height).toBe('400px');
        expect(guidance(host)!.scrollTop).toBe(120);
    });

    it('fits the field again when its width changes, not when only its height does', () => {
        const { host } = render(EDITOR);
        TestBed.tick();
        expect(guidance(host)!.style.height).toBe('40px');

        linesPerTextLine = 2;
        FakeResizeObserver.resize(guidance(host)!, 300);

        expect(guidance(host)!.style.height).toBe('60px');

        linesPerTextLine = 1;
        FakeResizeObserver.resize(guidance(host)!, 300);

        expect(guidance(host)!.style.height).toBe('60px');
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
