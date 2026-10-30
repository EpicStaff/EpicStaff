import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, BulkDeleteGroup, BulkDeleteResponse, ResourceCode } from '@shared/models';
import { BulkDeleteService } from '@shared/services';
import { map, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { GraphVersionDto } from '../../models/graph.model';
import { CreateGraphWarningsService } from '../../services/create-graph-warnings.service';
import { FlowsApiService } from '../../services/flows-api.service';
import { VersionHistoryPanelComponent } from './version-history-panel.component';

const SECRETS_REFUSAL_MESSAGE =
    'This contains code that reads secrets. This action requires the Use permission on secrets.';

const VERSIONS: GraphVersionDto[] = [
    { id: 1, graph_id: 7, name: 'First', description: '', created_at: '2026-09-01T10:00:00Z' },
    { id: 2, graph_id: 7, name: 'Second', description: 'Second description', created_at: '2026-09-02T10:00:00Z' },
];

function deletedResponse(ids: number[]): BulkDeleteResponse {
    return {
        dry_run: false,
        deleted_count: ids.length,
        deleted_ids: ids,
        deletable_ids: ids,
        not_found_ids: [],
        skipped: [],
        usage: {},
    };
}

describe('VersionHistoryPanelComponent', () => {
    let fixture: ComponentFixture<VersionHistoryPanelComponent>;
    let component: VersionHistoryPanelComponent;
    let flowsApi: {
        getGraphVersions: ReturnType<typeof vi.fn>;
        bulkDeleteGraphVersions: ReturnType<typeof vi.fn>;
        updateGraphVersion: ReturnType<typeof vi.fn>;
        createGraphFromVersion: ReturnType<typeof vi.fn>;
    };
    let navigate: ReturnType<typeof vi.fn>;
    let toast: {
        success: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
    };
    let confirmationDialog: { confirm: ReturnType<typeof vi.fn> };
    let previewed: GraphVersionDto[];
    let deleted: GraphVersionDto[];
    /** Read when a panel is created; every other action is always granted. */
    let isDeleteGranted: boolean;

    beforeEach(() => {
        isDeleteGranted = true;
        // The card's overflow tooltips observe their size; jsdom has no ResizeObserver.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        flowsApi = {
            getGraphVersions: vi.fn().mockReturnValue(of(VERSIONS)),
            bulkDeleteGraphVersions: vi.fn((ids: number[]) => of(deletedResponse(ids))),
            updateGraphVersion: vi.fn(),
            createGraphFromVersion: vi.fn(),
        };
        navigate = vi.fn().mockResolvedValue(true);
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn() };
        // Only the OK-only trigger-node refusal opens it; its result is never read.
        confirmationDialog = { confirm: vi.fn() };
        // Stands in for the preview + confirmation dialog as if the user confirmed: runs the panel's own delete target.
        const bulkDelete = {
            run: vi.fn((groups: BulkDeleteGroup[]) =>
                groups[0].target
                    .bulkDelete(groups[0].items.map((item) => item.id))
                    .pipe(map((response) => [{ group: groups[0], response }]))
            ),
        };

        TestBed.configureTestingModule({
            imports: [VersionHistoryPanelComponent],
            providers: [
                { provide: FlowsApiService, useValue: flowsApi as unknown as FlowsApiService },
                { provide: BulkDeleteService, useValue: bulkDelete as unknown as BulkDeleteService },
                {
                    provide: ConfirmationDialogService,
                    useValue: confirmationDialog as unknown as ConfirmationDialogService,
                },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (_resource: ResourceCode, action: ActionCode) =>
                            action !== ActionCode.Delete || isDeleteGranted,
                        canAny: (_resource: ResourceCode, actions: ActionCode[]) =>
                            actions.some((action) => action !== ActionCode.Delete || isDeleteGranted),
                    } as unknown as PermissionsService,
                },
                { provide: ToastService, useValue: toast as unknown as ToastService },
                { provide: Router, useValue: { navigate } as unknown as Router },
                {
                    provide: CreateGraphWarningsService,
                    useValue: { setPending: vi.fn() } as unknown as CreateGraphWarningsService,
                },
            ],
        });

        fixture = TestBed.createComponent(VersionHistoryPanelComponent);
        component = fixture.componentInstance;
        fixture.componentRef.setInput('graphId', 7);

        previewed = [];
        deleted = [];
        component.previewRequested.subscribe((version) => previewed.push(version));
        component.versionDeleted.subscribe((version) => deleted.push(version));

        fixture.detectChanges();
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        document.querySelectorAll('.cdk-overlay-container').forEach((container) => container.remove());
    });

    function cards(): HTMLElement[] {
        return Array.from(fixture.nativeElement.querySelectorAll('.version-card'));
    }

    function click(element: Element, detail = 1): void {
        element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, detail }));
    }

    function openMenu(cardIndex: number): void {
        cards()[cardIndex].querySelector<HTMLButtonElement>('.version-menu button')!.click();
        fixture.detectChanges();
    }

    function menuItemLabels(): string[] {
        return Array.from(document.querySelectorAll<HTMLButtonElement>('.action-dropdown-panel__item')).map(
            (button) => button.textContent?.trim() ?? ''
        );
    }

    function openMenuAndClick(cardIndex: number, itemLabel: string): void {
        openMenu(cardIndex);

        const item = Array.from(document.querySelectorAll<HTMLButtonElement>('.action-dropdown-panel__item')).find(
            (button) => button.textContent?.trim() === itemLabel
        );
        expect(item).toBeDefined();
        item!.click();
        fixture.detectChanges();
    }

    it('requests the preview on card click but leaves selection to the parent', () => {
        click(cards()[1].querySelector('.version-date')!);
        fixture.detectChanges();

        expect(previewed).toEqual([VERSIONS[1]]);
        expect(cards()[1].getAttribute('aria-pressed')).toBe('false');
    });

    it('marks the card selected by the parent', () => {
        fixture.componentRef.setInput('selectedVersionId', 2);
        fixture.detectChanges();

        expect(cards()[1].getAttribute('aria-pressed')).toBe('true');
        expect(cards()[0].getAttribute('aria-pressed')).toBe('false');
    });

    it.each(['Enter', ' '])('requests the preview on %j keydown', (key) => {
        const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
        cards()[0].dispatchEvent(event);
        fixture.detectChanges();

        expect(event.defaultPrevented).toBe(true);
        expect(previewed).toEqual([VERSIONS[0]]);
    });

    it('requests the preview again when the same card is clicked again', () => {
        click(cards()[0]);
        click(cards()[0]);

        expect(previewed).toEqual([VERSIONS[0], VERSIONS[0]]);
    });

    it('ignores the second click of a double-click outside the name/description', () => {
        click(cards()[0], 1);
        click(cards()[0], 2);

        expect(previewed).toEqual([VERSIONS[0]]);
    });

    it('ignores clicks and Enter/Space inside the rename input', () => {
        component.startEdit(VERSIONS[0], 'name');
        fixture.detectChanges();
        const input = cards()[0].querySelector<HTMLInputElement>('.version-edit-input');

        input!.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }));
        click(input!);
        fixture.detectChanges();

        expect(previewed).toEqual([]);
    });

    it('does not offer Preview in the options menu', () => {
        openMenu(0);

        expect(menuItemLabels()).toContain('Restore');
        expect(menuItemLabels()).not.toContain('Preview');
    });

    describe('new flow from a version', () => {
        let closedCount: number;

        beforeEach(() => {
            closedCount = 0;
            component.closed.subscribe(() => closedCount++);
        });

        it('opens the new flow', () => {
            flowsApi.createGraphFromVersion.mockReturnValue(of({ created: true, graph_id: 42, warnings: [] }));

            openMenuAndClick(0, 'Create flow from this');

            expect(flowsApi.createGraphFromVersion).toHaveBeenCalledExactlyOnceWith(VERSIONS[0].id);
            expect(toast.success).toHaveBeenCalledWith('New flow created');
            expect(navigate).toHaveBeenCalledWith(['/flows', 42]);
            expect(closedCount).toBe(1);
        });

        it('explains a refusal over trigger nodes, with no toast, no navigation and the panel left open', () => {
            flowsApi.createGraphFromVersion.mockReturnValue(
                throwError(
                    () =>
                        new HttpErrorResponse({
                            status: 403,
                            error: {
                                status_code: 403,
                                code: 'flow_with_trigger_nodes_requires_use_permission',
                                message: 'This flow contains trigger nodes.',
                            },
                        })
                )
            );

            openMenuAndClick(0, 'Create flow from this');

            expect(confirmationDialog.confirm).toHaveBeenCalledExactlyOnceWith(
                expect.objectContaining({
                    message: 'This version contains trigger nodes (Webhook, Telegram, Schedule).',
                    caution:
                        '<strong>Creating a flow</strong> from it requires the <strong>Use</strong> permission on flows.',
                    hideConfirm: true,
                })
            );
            expect(toast.success).not.toHaveBeenCalled();
            expect(toast.error).not.toHaveBeenCalled();
            expect(navigate).not.toHaveBeenCalled();
            expect(closedCount).toBe(0);
        });

        it('reports any other failure', () => {
            flowsApi.createGraphFromVersion.mockReturnValue(
                throwError(() => new HttpErrorResponse({ status: 500, statusText: 'Server Error' }))
            );

            openMenuAndClick(0, 'Create flow from this');

            expect(toast.error).toHaveBeenCalledWith('Failed to create flow');
            expect(confirmationDialog.confirm).not.toHaveBeenCalled();
            expect(navigate).not.toHaveBeenCalled();
        });

        it('explains a refusal over code that reads secrets, with no toast and no navigation', () => {
            flowsApi.createGraphFromVersion.mockReturnValue(
                throwError(
                    () =>
                        new HttpErrorResponse({
                            status: 403,
                            error: {
                                status_code: 403,
                                code: 'code_with_secrets_requires_secrets_use_permission',
                                message: SECRETS_REFUSAL_MESSAGE,
                            },
                        })
                )
            );

            openMenuAndClick(0, 'Create flow from this');

            expect(confirmationDialog.confirm).toHaveBeenCalledExactlyOnceWith(
                expect.objectContaining({
                    title: 'Use permission required',
                    message: 'This version contains code that reads secrets.',
                    caution:
                        '<strong>Creating a flow</strong> from it requires the <strong>Use</strong> permission on secrets.',
                })
            );
            expect(toast.error).not.toHaveBeenCalled();
            expect(navigate).not.toHaveBeenCalled();
        });
    });

    describe('name/description clicks (double-click renames)', () => {
        beforeEach(() => vi.useFakeTimers());
        afterEach(() => vi.useRealTimers());

        it('starts a rename on double-click of the name without requesting a preview or selecting', () => {
            const name = cards()[0].querySelector('.version-name')!;

            click(name, 1);
            click(name, 2);
            name.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true, detail: 2 }));
            vi.runAllTimers();
            fixture.detectChanges();

            expect(component.editingVersionId).toBe(1);
            expect(component.editingField).toBe('name');
            expect(previewed).toEqual([]);
        });

        it('requests the preview after the double-click window on a single click of the description', () => {
            click(cards()[1].querySelector('.version-description')!);
            expect(previewed).toEqual([]);

            vi.advanceTimersByTime(250);

            expect(previewed).toEqual([VERSIONS[1]]);
        });

        it('drops the pending preview when another card is clicked meanwhile', () => {
            click(cards()[0].querySelector('.version-name')!);
            click(cards()[1]);
            vi.runAllTimers();

            expect(previewed).toEqual([VERSIONS[1]]);
        });

        it('drops the pending preview when the panel is destroyed', () => {
            click(cards()[0].querySelector('.version-name')!);
            fixture.destroy();
            vi.runAllTimers();

            expect(previewed).toEqual([]);
        });
    });

    it('neither selects nor requests a preview when the options button is clicked', () => {
        openMenu(1);

        expect(previewed).toEqual([]);
    });

    it('removes the card and emits versionDeleted when a version is deleted', () => {
        openMenuAndClick(1, 'Delete');

        expect(flowsApi.bulkDeleteGraphVersions).toHaveBeenCalledWith([2]);
        expect(deleted).toEqual([VERSIONS[1]]);
        expect(cards().length).toBe(1);
    });

    it('toggles the card instead of requesting a preview while selecting', () => {
        component.enterSelectMode();
        fixture.detectChanges();

        click(cards()[0].querySelector('.version-date')!);
        fixture.detectChanges();

        expect(previewed).toEqual([]);
        expect(component.isVersionSelected(1)).toBe(true);
        expect(cards()[0].getAttribute('aria-pressed')).toBe('true');
    });

    it('gives each row a secondary (light box, dark tick) selection checkbox', () => {
        component.enterSelectMode();
        fixture.detectChanges();

        const checkboxes = cards().map((card) => card.querySelector('.version-checkbox app-checkbox input'));
        expect(checkboxes).toHaveLength(VERSIONS.length);
        checkboxes.forEach((checkbox) => expect(checkbox?.classList).toContain('secondary'));
    });

    describe('select dropdown', () => {
        function selectButton(): HTMLButtonElement {
            return fixture.nativeElement.querySelector('app-bulk-select-dropdown .bulk-select__main');
        }

        function selectAllItem(): HTMLButtonElement {
            return document.querySelector<HTMLButtonElement>('.bulk-select-menu__item')!;
        }

        function footerDelete(): HTMLButtonElement {
            return fixture.nativeElement.querySelector('.footer-delete-button button');
        }

        it('enters select mode from the header and selects every version with "Select All"', () => {
            selectButton().click();
            fixture.detectChanges();
            expect(component.selectMode()).toBe(true);
            expect(footerDelete().disabled).toBe(true);

            selectAllItem().click();
            fixture.detectChanges();

            expect(component.isVersionSelected(1)).toBe(true);
            expect(component.isVersionSelected(2)).toBe(true);
            expect(footerDelete().textContent?.trim()).toBe('Delete');
            expect(footerDelete().classList).toContain('btn-danger');
            expect(footerDelete().disabled).toBe(false);
        });

        it('puts the trash icon inside the Delete label, next to the text', () => {
            selectButton().click();
            fixture.detectChanges();

            const icon = footerDelete().querySelector('.btn-content app-svg-icon use');
            expect(icon?.getAttribute('href')).toBe('#icon-trash');
            expect(footerDelete().querySelector('.btn-icon')).toBeNull();
        });

        it('offers "Deselect All" once every version is selected, and it clears the selection', () => {
            selectButton().click();
            fixture.detectChanges();
            selectAllItem().click();
            fixture.detectChanges();

            selectButton().click();
            fixture.detectChanges();
            expect(selectAllItem().textContent?.trim()).toBe('Deselect All');
            selectAllItem().click();
            fixture.detectChanges();

            expect(component.selectedCount()).toBe(0);
            expect(component.selectMode()).toBe(true);
        });

        it('leaves select mode and clears the selection with the ×', () => {
            selectButton().click();
            fixture.detectChanges();
            click(cards()[0]);
            fixture.detectChanges();

            fixture.nativeElement.querySelector('.bulk-select__clear').click();
            fixture.detectChanges();

            expect(component.selectMode()).toBe(false);
            expect(component.selectedCount()).toBe(0);
            expect(fixture.nativeElement.querySelector('.restore-version-btn')).not.toBeNull();
        });

        it('offers neither the select dropdown nor any Delete without the delete permission', () => {
            isDeleteGranted = false;
            fixture = TestBed.createComponent(VersionHistoryPanelComponent);
            component = fixture.componentInstance;
            fixture.componentRef.setInput('graphId', 7);
            fixture.detectChanges();

            expect(fixture.nativeElement.querySelector('app-bulk-select-dropdown')).toBeNull();
            expect(fixture.nativeElement.querySelector('.footer-delete-button')).toBeNull();
            openMenu(0);
            expect(menuItemLabels()).toContain('Restore');
            expect(menuItemLabels()).not.toContain('Delete');
        });
    });

    it('treats a double-click as a single toggle while selecting', () => {
        component.enterSelectMode();
        fixture.detectChanges();

        click(cards()[0], 1);
        click(cards()[0], 2);
        click(cards()[1].querySelector('.version-name')!, 1);
        click(cards()[1].querySelector('.version-name')!, 2);

        expect(component.isVersionSelected(1)).toBe(true);
        expect(component.isVersionSelected(2)).toBe(true);
    });

    it('emits the updated version after a successful rename', () => {
        const renamed = { ...VERSIONS[0], name: 'Renamed' };
        flowsApi.updateGraphVersion.mockReturnValue(of(renamed));
        const updated: GraphVersionDto[] = [];
        component.versionUpdated.subscribe((version) => updated.push(version));
        component.startEdit(VERSIONS[0], 'name');
        component.editingValue = 'Renamed';

        component.saveEdit(VERSIONS[0]);

        expect(updated).toEqual([renamed]);
    });

    it('rejects a blank rename with a message instead of sending it', () => {
        component.startEdit(VERSIONS[0], 'name');
        component.editingValue = '   ';

        component.saveEdit(VERSIONS[0]);

        expect(flowsApi.updateGraphVersion).not.toHaveBeenCalled();
        expect(toast.warning).toHaveBeenCalledWith('Version name is required');
        expect(component.editingVersionId).toBeNull();
    });

    it('offers the full name and description as tooltips on the card', () => {
        const tooltips = fixture.debugElement
            .queryAll(By.directive(MatTooltip))
            .map((element) => element.injector.get(MatTooltip).message);

        expect(tooltips).toContain(VERSIONS[1].name);
        expect(tooltips).toContain(VERSIONS[1].description);
    });

    it('keeps the latest load when an earlier, slower load finishes after it', () => {
        const earlierLoad = new Subject<GraphVersionDto[]>();
        const laterLoad = new Subject<GraphVersionDto[]>();
        flowsApi.getGraphVersions.mockReturnValueOnce(earlierLoad).mockReturnValueOnce(laterLoad);

        component.isLoading = true;
        component.loadVersions();
        component.loadVersions();
        expect(component.isLoading).toBe(true);
        laterLoad.next([VERSIONS[1]]);
        earlierLoad.next([VERSIONS[0]]);

        expect(component.versionsList).toEqual([VERSIONS[1]]);
        expect(component.isLoading).toBe(false);
        expect(earlierLoad.observed).toBe(false);
    });

    it('highlights the previewed version', () => {
        fixture.componentRef.setInput('previewedVersionId', 2);
        fixture.detectChanges();

        expect(cards()[1].classList).toContain('version-card--previewed');
        expect(cards()[0].classList).not.toContain('version-card--previewed');
    });
});
