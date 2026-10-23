import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { NgZone, NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltipModule } from '@angular/material/tooltip';
import { FFlowModule, FZoomDirective } from '@foblex/flow';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';
import { of } from 'rxjs';

import { SelectStorageFilesDialogComponent } from '../../features/files/components/select-storage-files-dialog/select-storage-files-dialog.component';
import { ToastService } from '../../services/notifications';
import { DomainDialogComponent } from '../components/domain-dialog/domain-dialog.component';
import { FlowExportImportButtonComponent } from '../components/flow-export-import-button/flow-export-import-button.component';
import { FlowFilesButtonComponent } from '../components/flow-files-button/flow-files-button.component';
import { FlowSettingsPanelComponent } from '../components/flow-settings-panel/flow-settings-panel.component';
import { FlowShortcutsButtonComponent } from '../components/flow-shortcuts-button/flow-shortcuts-button.component';
import { generatePortsForNode } from '../core/helpers/helpers';
import { NodeModel } from '../core/models/node.model';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';
import { FlowService } from '../services/flow.service';
import { PLATFORM_IS_MAC } from '../services/keymap.service';
import { NodeAuthorshipStore } from '../services/node-authorship.store';
import { VersionPreviewNodeAuthorshipStore } from '../services/version-preview-node-authorship.store';
import { createStartNode } from '../utils/load';
import { FLOW_ACTIONS_WITH_USE, grantPermissions } from '../utils/testing/permissions.fixture';
import { FlowGraphComponent } from './flow-graph.component';

/**
 * The canvas toolbar keys, pressed the way a user presses them (a keydown that reaches the window), against the
 * real toolbar template, the real Foblex canvas and the real export/import and files buttons. Dialogs are a stub:
 * what a key opens is read from what was asked of the dialog service.
 */

const READ_ONLY_MESSAGE = 'You have read-only access to this flow.';
const PREVIEW_MESSAGE = 'Preview mode is read-only. Exit preview to edit the flow';
const FLOW_ID = 3;

const AUTO_ARRANGE = { code: 'KeyL', key: 'l', altKey: true };
const ADD_FILES = { code: 'KeyU', key: 'u', altKey: true };
const EXPORT_IMPORT = { code: 'KeyX', key: 'x', altKey: true };
const EXTRACT_SUBFLOW = { code: 'KeyG', key: 'g', altKey: true };
const SETTINGS = { code: 'Comma', key: ',', altKey: true };
const DOMAIN = { code: 'KeyM', key: 'm', altKey: true };

function pythonNode(id: string, position: { x: number; y: number }): NodeModel {
    return {
        id,
        backendId: null,
        type: NodeType.PYTHON,
        node_name: id,
        data: {},
        position,
        ports: generatePortsForNode(id, NodeType.PYTHON),
        color: '',
        icon: '',
        size: { width: 200, height: 100 },
        input_map: {},
        output_variable_path: null,
    } as unknown as NodeModel;
}

interface MountOptions {
    readonly isPreview?: boolean;
    readonly isMac?: boolean;
    readonly flowActions?: ActionCode[];
    readonly fileActions?: ActionCode[];
}

describe('FlowGraphComponent canvas toolbar keys', () => {
    let fixture: ComponentFixture<FlowGraphComponent>;
    let flowService: FlowService;
    let dialog: { open: ReturnType<typeof vi.fn>; openDialogs: unknown[] };
    let info: ReturnType<typeof vi.spyOn>;
    const attached: HTMLElement[] = [];

    function mount(options: MountOptions = {}): FlowGraphComponent {
        // jsdom has neither layout nor ResizeObserver; Foblex only needs the observer to exist.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        // Foblex warns that a canvas jsdom cannot lay out has zero height.
        vi.spyOn(console, 'warn').mockImplementation(() => undefined);
        vi.spyOn(console, 'error').mockImplementation(() => undefined);
        dialog = { open: vi.fn().mockReturnValue({ closed: of(undefined) }), openDialogs: [] };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: Dialog, useValue: dialog },
                { provide: FLOW_EDITOR_PREVIEW, useValue: options.isPreview ?? false },
                { provide: PLATFORM_IS_MAC, useValue: options.isMac ?? false },
                ...(options.isPreview
                    ? [
                          VersionPreviewNodeAuthorshipStore,
                          { provide: NodeAuthorshipStore, useExisting: VersionPreviewNodeAuthorshipStore },
                      ]
                    : [NodeAuthorshipStore]),
            ],
        });
        // The editor's other children (nodes, side panel, node search…) render as unknown elements.
        TestBed.overrideComponent(FlowGraphComponent, {
            set: {
                imports: [
                    FFlowModule,
                    FZoomDirective,
                    MatTooltipModule,
                    HasPermissionDirective,
                    FlowExportImportButtonComponent,
                    FlowFilesButtonComponent,
                    FlowShortcutsButtonComponent,
                ],
                schemas: [NO_ERRORS_SCHEMA],
            },
        });
        grantPermissions({
            [ResourceCode.Flows]: options.flowActions ?? [...FLOW_ACTIONS_WITH_USE, ActionCode.Export],
            [ResourceCode.Files]: options.fileActions ?? [ActionCode.Read],
        });
        info = vi.spyOn(TestBed.inject(ToastService), 'info').mockImplementation(() => undefined);
        flowService = TestBed.inject(FlowService);
        fixture = TestBed.createComponent(FlowGraphComponent);
        fixture.componentRef.setInput('flowState', {
            nodes: [
                createStartNode(),
                pythonNode('python-1', { x: 600, y: 0 }),
                pythonNode('python-2', { x: 600, y: 300 }),
            ],
            connections: [],
        });
        fixture.componentRef.setInput('currentFlowId', FLOW_ID);
        fixture.componentRef.setInput('flowName', 'Support flow');
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    function press(init: KeyboardEventInit, target: EventTarget = window): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
        target.dispatchEvent(event);
        fixture.detectChanges();
        return event;
    }

    function host(): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    function openedDialogs(): unknown[] {
        return dialog.open.mock.calls.map(([component]) => component);
    }

    function selectNodes(...nodeIds: string[]): void {
        fixture.debugElement
            .query((element) => element.name === 'f-flow')
            .triggerEventHandler('fSelectionChange', {
                nodeIds,
            });
        fixture.detectChanges();
    }

    function nodePosition(id: string): { x: number; y: number } | undefined {
        return flowService.nodes().find((node) => node.id === id)?.position;
    }

    function exportMenuItems(): HTMLButtonElement[] {
        return [...document.querySelectorAll<HTMLButtonElement>('.action-dropdown-panel__item')];
    }

    function insideSidePanel<T extends HTMLElement>(element: T): T {
        host().querySelector('app-node-panel-shell')!.appendChild(element);
        return element;
    }

    function attach<T extends HTMLElement>(element: T): T {
        document.body.appendChild(element);
        attached.push(element);
        return element;
    }

    afterEach(() => {
        attached.splice(0).forEach((element) => element.remove());
        fixture?.destroy();
        vi.useRealTimers();
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    describe('each key does what its button does', () => {
        it.each([
            ['Alt+M', DOMAIN, '.domain-button', DomainDialogComponent],
            ['Alt+,', SETTINGS, '.settings-icon-btn', FlowSettingsPanelComponent],
            ['Alt+U', ADD_FILES, '.flow-files-btn', SelectStorageFilesDialogComponent],
        ])('%s opens the same window as its button', (_key, key, buttonSelector, dialogComponent) => {
            mount();

            press(key);
            host().querySelector<HTMLButtonElement>(buttonSelector)!.click();

            expect(openedDialogs()).toEqual([dialogComponent, dialogComponent]);
        });

        it('Alt+U opens the files of this flow', () => {
            mount();

            press(ADD_FILES);

            expect(dialog.open.mock.calls[0][1].data).toEqual({ flowId: FLOW_ID, flowName: 'Support flow' });
        });

        it('Alt+L arranges the flow like the Auto arrange button', () => {
            mount();
            vi.useFakeTimers();

            press(AUTO_ARRANGE);
            vi.advanceTimersByTime(1000);

            expect([nodePosition('python-1'), nodePosition('python-2')]).not.toEqual([
                { x: 600, y: 0 },
                { x: 600, y: 300 },
            ]);
        });

        it('Alt+X opens the Export / Import menu with the keyboard focus on its first item, and closes it again', () => {
            mount();

            press(EXPORT_IMPORT);
            TestBed.tick();

            expect(exportMenuItems().map((item) => item.textContent?.trim())).toEqual(['Export All as JSON', 'Import']);
            expect(document.activeElement).toBe(exportMenuItems()[0]);

            press(EXPORT_IMPORT, document.activeElement!);

            expect(exportMenuItems()).toEqual([]);
        });

        // A real key press starts at the focused element, so Angular CDK sees it and treats the focus that follows
        // as keyboard focus; the menu items have tooltips, which show on keyboard focus.
        it.each([
            ['Alt+X', () => press(EXPORT_IMPORT, document.body)],
            ['a click', () => host().querySelector<HTMLButtonElement>('.feib')!.click()],
        ])('one Esc closes the menu opened with %s and still ends multi-select', (_opener, openMenu) => {
            const component = mount();
            vi.useFakeTimers();
            component.onToggleMultiSelect();
            // Inside the Angular zone, where the app's own change detection runs.
            TestBed.inject(NgZone).run(() => {
                openMenu();
                fixture.detectChanges();
                TestBed.tick();
            });
            // Long enough for a tooltip to show.
            vi.advanceTimersByTime(1000);
            fixture.detectChanges();
            expect(exportMenuItems()).not.toEqual([]);
            expect(document.querySelector('.mat-mdc-tooltip')).toBeNull();

            // keyCode as a browser sets it: the CDK overlay closes on Esc by keyCode.
            press({ code: 'Escape', key: 'Escape', keyCode: 27 }, document.activeElement ?? document.body);

            expect(exportMenuItems()).toEqual([]);
            expect(component.selectionManager.multiSelectActive()).toBe(false);
        });

        it('Alt+G extracts the selected nodes into a subflow like the Extract to Subflow button', () => {
            const component = mount();
            const extracted: Set<string>[] = [];
            component.extractToSubflow.subscribe((ids) => extracted.push(ids));
            selectNodes('python-1', 'python-2');

            press(EXTRACT_SUBFLOW);
            host().querySelector<HTMLButtonElement>('.extract-subflow-btn')!.click();

            expect(extracted).toEqual([new Set(['python-1', 'python-2']), new Set(['python-1', 'python-2'])]);
        });

        it('Alt+G does nothing without a selection, where the button is not shown', () => {
            const component = mount();
            const extracted: Set<string>[] = [];
            component.extractToSubflow.subscribe((ids) => extracted.push(ids));

            press(EXTRACT_SUBFLOW);

            expect(host().querySelector('.extract-subflow-btn')).toBeNull();
            expect(extracted).toEqual([]);
            expect(info).not.toHaveBeenCalled();
        });

        it.each([
            ['Alt+L', AUTO_ARRANGE],
            ['Alt+U', ADD_FILES],
            ['Alt+X', EXPORT_IMPORT],
            ['Alt+,', SETTINGS],
            ['Alt+M', DOMAIN],
        ])('%s keeps the browser from acting on the key too', (_key, key) => {
            mount();

            expect(press(key).defaultPrevented).toBe(true);
        });
    });

    describe('where the button is not shown', () => {
        it('a viewer gets no arrangement on Alt+L, and the read-only message', () => {
            mount({ flowActions: [ActionCode.Read] });
            vi.useFakeTimers();

            press(AUTO_ARRANGE);
            vi.advanceTimersByTime(1000);

            expect(nodePosition('python-1')).toEqual({ x: 600, y: 0 });
            expect(info).toHaveBeenCalledExactlyOnceWith(READ_ONLY_MESSAGE);
        });

        it('a viewer who may neither export nor import gets no menu on Alt+X, and the read-only message', () => {
            mount({ flowActions: [ActionCode.Read] });

            press(EXPORT_IMPORT);
            TestBed.tick();

            expect(exportMenuItems()).toEqual([]);
            expect(info).toHaveBeenCalledExactlyOnceWith(READ_ONLY_MESSAGE);
        });

        it('a viewer who may export gets the menu with Export only', () => {
            mount({ flowActions: [ActionCode.Read, ActionCode.Export] });

            press(EXPORT_IMPORT);
            TestBed.tick();

            expect(exportMenuItems().map((item) => item.textContent?.trim())).toEqual(['Export All as JSON']);
        });

        it('a user without access to files gets no files window on Alt+U', () => {
            mount({ fileActions: [] });

            press(ADD_FILES);

            expect(host().querySelector('.flow-files-btn')).toBeNull();
            expect(openedDialogs()).toEqual([]);
        });

        it.each([
            ['Alt+L', AUTO_ARRANGE],
            ['Alt+U', ADD_FILES],
            ['Alt+X', EXPORT_IMPORT],
            ['Alt+G', EXTRACT_SUBFLOW],
        ])('in a version preview %s does nothing and says the preview is read-only', (_key, key) => {
            const component = mount({ isPreview: true });
            const extracted: Set<string>[] = [];
            component.extractToSubflow.subscribe((ids) => extracted.push(ids));
            selectNodes('python-1');
            vi.useFakeTimers();

            press(key);
            vi.advanceTimersByTime(1000);
            TestBed.tick();

            expect(openedDialogs()).toEqual([]);
            expect(exportMenuItems()).toEqual([]);
            expect(extracted).toEqual([]);
            expect(nodePosition('python-1')).toEqual({ x: 600, y: 0 });
            expect(info).toHaveBeenCalledExactlyOnceWith(PREVIEW_MESSAGE, 3000, 'bottom-right');
        });

        it.each([
            ['Alt+M', DOMAIN, DomainDialogComponent],
            ['Alt+,', SETTINGS, FlowSettingsPanelComponent],
        ])(
            'in a version preview %s still opens its window, as the button is shown there',
            (_key, key, dialogComponent) => {
                mount({ isPreview: true });

                press(key);

                expect(openedDialogs()).toEqual([dialogComponent]);
            }
        );
    });

    describe('when the keys fire', () => {
        it('fires nothing while a dialog is open', () => {
            const component = mount();
            const extracted: Set<string>[] = [];
            component.extractToSubflow.subscribe((ids) => extracted.push(ids));
            selectNodes('python-1');
            dialog.openDialogs.push({});
            vi.useFakeTimers();

            for (const key of [AUTO_ARRANGE, ADD_FILES, EXPORT_IMPORT, EXTRACT_SUBFLOW, SETTINGS, DOMAIN]) {
                press(key);
            }
            vi.advanceTimersByTime(1000);
            TestBed.tick();

            expect(openedDialogs()).toEqual([]);
            expect(exportMenuItems()).toEqual([]);
            expect(extracted).toEqual([]);
            expect(nodePosition('python-1')).toEqual({ x: 600, y: 0 });
        });

        it('fires nothing while the node menu is open', () => {
            mount();
            host()
                .querySelector('f-flow')!
                .dispatchEvent(new MouseEvent('contextmenu', { clientX: 40, clientY: 40, bubbles: true }));
            fixture.detectChanges();

            press(DOMAIN);

            expect(openedDialogs()).toEqual([]);
        });

        it('tells the page whether the node menu is open, so its own keys can stay off meanwhile', () => {
            const component = mount();
            const flowHost = host().querySelector('f-flow')!;

            flowHost.dispatchEvent(new MouseEvent('contextmenu', { clientX: 40, clientY: 40, bubbles: true }));
            const openWhileShown = component.isNodeMenuOpen();
            component.onCloseContextMenu();

            expect([openWhileShown, component.isNodeMenuOpen()]).toEqual([true, false]);
        });

        it('fires nothing while typing in a text field', () => {
            mount();

            press(DOMAIN, attach(document.createElement('input')));
            press(SETTINGS, insideSidePanel(document.createElement('textarea')));

            expect(openedDialogs()).toEqual([]);
        });

        it('fires with the focus in the side panel outside a text field', () => {
            mount();

            press(DOMAIN, insideSidePanel(document.createElement('button')));

            expect(openedDialogs()).toEqual([DomainDialogComponent]);
        });

        it('fires once while the key is held down', () => {
            mount();

            press(DOMAIN);
            press({ ...DOMAIN, repeat: true });
            press({ ...DOMAIN, repeat: true });

            expect(openedDialogs()).toEqual([DomainDialogComponent]);
        });
    });

    describe('Multi-select hint', () => {
        it.each([
            ['Windows', false],
            ['a Mac', true],
        ])('shows the Shift symbol on %s, as the word does not fit the button', (_platform, isMac) => {
            mount({ isMac });

            const multiSelect = host().querySelector('app-flow-shortcuts-button[icon="multi-select"]')!;

            expect(multiSelect.querySelector('.flow-shortcuts-btn__text')?.textContent?.trim()).toBe('⇧');
            // Read out as "Multi-select", not as the arrow symbol.
            expect(multiSelect.querySelector('button')?.getAttribute('aria-label')).toBe('Multi-select');
        });
    });
});
