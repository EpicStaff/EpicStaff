import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NgZone, Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, DEFAULT_USER_PREFERENCES, GetMeResponse, ResourceCode, ShortcutSettings } from '@shared/models';

import { PLATFORM_IS_MAC } from '../../../../core/services/platform-is-mac.token';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { ToastMessage, ToastService } from '../../../../services/notifications';
import { grantPermissions } from '../../../utils/testing/permissions.fixture';

/**
 * Shared by the specs of the shortcuts editor and of the components that host it: the test bed, the signed-in
 * user's saved shortcuts, the PATCH that saves them, and reading and driving the rendered list like a user.
 */

export const PROFILE_URL = '/api/profile/';

export const BASE_USER: GetMeResponse = {
    id: 7,
    email: 'jane@example.com',
    display_name: 'Jane Doe',
    is_superadmin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    memberships: [],
    active_organization_id: 3,
    active_permissions: null,
    avatar_url: null,
    completed_tours: ['quick-start'],
    custom_shortcuts: { overrides: {}, custom: [] },
    preferences: DEFAULT_USER_PREFERENCES,
};

/** Every permission a flow toolbar button checks, so every Flow actions row shows. */
export const EVERY_FLOW_PERMISSION: Partial<Record<ResourceCode, ActionCode[]>> = {
    [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update, ActionCode.Use, ActionCode.Export],
    [ResourceCode.Files]: [ActionCode.Read],
};

export interface RenderedRow {
    label: string;
    chords: string[][];
}

export interface RenderedCustomRow {
    label: string;
    keys: string;
}

export type CustomRow = ShortcutSettings['custom'][number];

export interface PendingPatch {
    body: unknown;
    succeed: () => void;
    fail: () => void;
}

/** Calls back only on `resize()`. Like the real one, several observers may watch one element (an `app-button`
 * watches the scrolling list it sits in, the editor watches it too). */
export class ResizeObserverStub {
    static observing = new Map<Element, Set<ResizeObserverStub>>();

    constructor(private readonly callback: ResizeObserverCallback) {}

    static resize(target: Element): void {
        ResizeObserverStub.observing
            .get(target)
            ?.forEach((observer) => observer.callback([], observer as unknown as ResizeObserver));
    }

    observe(target: Element): void {
        const observers = ResizeObserverStub.observing.get(target) ?? new Set<ResizeObserverStub>();
        observers.add(this);
        ResizeObserverStub.observing.set(target, observers);
    }
    unobserve(target: Element): void {
        ResizeObserverStub.observing.get(target)?.delete(this);
    }
    disconnect(): void {
        ResizeObserverStub.observing.forEach((observers) => observers.delete(this));
    }
}

// The specs call these helpers by name, as plain functions, so the fixture is a bag of closures, not a class.
export function createShortcutsFixture<T>(component: Type<T>) {
    let fixture: ComponentFixture<T> | null = null;
    let httpMock: HttpTestingController | null = null;
    let toasts: ToastMessage[] = [];
    let frames = new Map<number, FrameRequestCallback>();
    let lastFrameId = 0;

    function currentFixture(): ComponentFixture<T> {
        if (fixture === null) throw new Error('No component created yet');
        return fixture;
    }

    function http(): HttpTestingController {
        if (httpMock === null) throw new Error('setUp() was not called');
        return httpMock;
    }

    /** Animation frames wait in a queue that `render()` runs, so a spec sees every frame's outcome in order. */
    function setUp(isMac = false): void {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        frames = new Map();
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
            lastFrameId += 1;
            frames.set(lastFrameId, callback);
            return lastFrameId;
        });
        vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
        TestBed.configureTestingModule({
            imports: [component],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: PLATFORM_IS_MAC, useValue: isMac },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        grantPermissions(EVERY_FLOW_PERMISSION);
        toasts = [];
        TestBed.inject(ToastService).toasts$.subscribe((current) => (toasts = current));
    }

    function tearDown(): void {
        try {
            httpMock?.verify();
        } finally {
            fixture = null;
            httpMock = null;
            ResizeObserverStub.observing.clear();
            TestBed.resetTestingModule();
            vi.unstubAllGlobals();
            vi.restoreAllMocks();
            vi.useRealTimers();
        }
    }

    /** Creates the component with these inputs, without rendering it yet. */
    function create(inputs: Record<string, unknown> = {}): ComponentFixture<T> {
        fixture = TestBed.createComponent(component);
        for (const [name, value] of Object.entries(inputs)) {
            fixture.componentRef.setInput(name, value);
        }
        return fixture;
    }

    function loadUser(custom: CustomRow[]): void {
        loadSettings({ custom });
    }

    function loadSettings(settings: unknown): void {
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        http()
            .expectOne({ method: 'GET', url: PROFILE_URL })
            .flush({ ...BASE_USER, custom_shortcuts: settings });
    }

    function render(): void {
        const zone = TestBed.inject(NgZone);
        zone.run(() => {
            currentFixture().detectChanges();
            TestBed.tick();
        });
        for (let round = 0; round < 5 && frames.size > 0; round++) {
            const due = [...frames.values()];
            frames.clear();
            zone.run(() => {
                due.forEach((callback) => callback(0));
                currentFixture().detectChanges();
                TestBed.tick();
            });
        }
    }

    function nextPatch(): PendingPatch {
        const request = http().expectOne({ method: 'PATCH', url: PROFILE_URL });
        const body = request.request.body as { custom_shortcuts: ShortcutSettings };
        return {
            body,
            succeed: () => {
                request.flush({ ...BASE_USER, custom_shortcuts: body.custom_shortcuts });
                render();
            },
            fail: () => {
                request.flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
                render();
            },
        };
    }

    function text(element: Element): string {
        return (element.textContent ?? '').replace(/\s+/g, ' ').trim();
    }

    function root(): HTMLElement {
        return currentFixture().nativeElement;
    }

    function sectionTitles(): string[] {
        return Array.from(root().querySelectorAll('.shortcuts__card-title'), text);
    }

    function cardOf(sectionTitle: string): Element {
        const card = Array.from(root().querySelectorAll('.shortcuts__card') as NodeListOf<Element>).find(
            (candidate) => text(candidate.querySelector('.shortcuts__card-title')!) === sectionTitle
        );
        if (!card) throw new Error(`No "${sectionTitle}" section rendered`);
        return card;
    }

    function rowsOf(sectionTitle: string): RenderedRow[] {
        return rowElementsOf(sectionTitle).map(readRow);
    }

    function rowElementsOf(sectionTitle: string): Element[] {
        return Array.from(cardOf(sectionTitle).querySelectorAll('.shortcuts__row'));
    }

    function readRow(row: Element): RenderedRow {
        const chords: string[][] = [];
        row.querySelector('.shortcuts__keys')!.childNodes.forEach((node) => {
            if (!(node instanceof Element)) return;
            if (node.classList.contains('shortcuts__or')) {
                chords.push([]);
            } else if (node.classList.contains('shortcuts__key')) {
                if (chords.length === 0) chords.push([]);
                chords[chords.length - 1].push(text(node));
            } else if (node.classList.contains('shortcuts__arrow-keys')) {
                if (chords.length === 0) chords.push([]);
                chords[chords.length - 1].push(node.getAttribute('aria-label') ?? '');
            }
        });
        return { label: text(row.querySelector('.shortcuts__label')!), chords };
    }

    function nodeRow(label: string): string {
        const row = rowElementsOf('Nodes').find((candidate) => readRow(candidate).label === label)!;
        return text(row.querySelector('.shortcuts__keys')!);
    }

    function customRows(): RenderedCustomRow[] {
        return rowElementsOf('Additional').map((row) => ({
            label: text(row.querySelector('.shortcuts__label')!),
            keys: text(row.querySelector('.shortcuts__keys')!),
        }));
    }

    function buttonNamed(name: string, container: Element = root()): HTMLButtonElement {
        const button = Array.from(container.querySelectorAll('button')).find(
            (candidate) => (candidate.getAttribute('aria-label') ?? text(candidate)) === name
        );
        if (!button) throw new Error(`No "${name}" button rendered`);
        return button;
    }

    function hasButton(name: string, container: Element = root()): boolean {
        return Array.from(container.querySelectorAll('button')).some(
            (candidate) => (candidate.getAttribute('aria-label') ?? text(candidate)) === name
        );
    }

    function click(button: HTMLElement): void {
        button.click();
        render();
    }

    function editor(): HTMLElement | null {
        return root().querySelector('app-shortcut-editor');
    }

    function actionPicker(): HTMLInputElement {
        return editor()!.querySelector('input[role="combobox"]')!;
    }

    function keysBox(): HTMLButtonElement {
        return editor()!.querySelector('.shortcut-editor__recorder')!;
    }

    function saveButton(): HTMLButtonElement {
        return buttonNamed('Save', editor()!);
    }

    function feedback(): string {
        const message = editor()!.querySelector('.shortcut-editor__feedback');
        return message ? text(message) : '';
    }

    function pickAction(label: string): void {
        const input = actionPicker();
        input.focus();
        input.value = label.slice(0, 4);
        input.dispatchEvent(new Event('input'));
        render();
        const option = Array.from(editor()!.querySelectorAll('[role="option"]')).find(
            (candidate) => text(candidate) === label
        );
        if (!option) throw new Error(`No "${label}" option in the picker`);
        (option as HTMLElement).click();
        render();
    }

    function press(target: HTMLElement, init: KeyboardEventInit): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
        target.dispatchEvent(event);
        render();
        return event;
    }

    function record(init: KeyboardEventInit): KeyboardEvent {
        click(keysBox());
        return press(keysBox(), init);
    }

    function startAdding(): void {
        click(buttonNamed('Add shortcut'));
    }

    return {
        fixture: currentFixture,
        toasts: (): ToastMessage[] => toasts,
        setUp,
        tearDown,
        create,
        loadUser,
        loadSettings,
        render,
        nextPatch,
        text,
        root,
        sectionTitles,
        cardOf,
        rowsOf,
        rowElementsOf,
        readRow,
        nodeRow,
        customRows,
        buttonNamed,
        hasButton,
        click,
        editor,
        actionPicker,
        keysBox,
        saveButton,
        feedback,
        pickAction,
        press,
        record,
        startAdding,
    };
}
