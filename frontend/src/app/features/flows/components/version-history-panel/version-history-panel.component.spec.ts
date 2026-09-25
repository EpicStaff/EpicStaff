import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ConfirmationDialogService } from '@shared/components';
import { of } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { GraphVersionDto } from '../../models/graph.model';
import { CreateGraphWarningsService } from '../../services/create-graph-warnings.service';
import { FlowsApiService } from '../../services/flows-api.service';
import { VersionHistoryPanelComponent } from './version-history-panel.component';

const VERSIONS: GraphVersionDto[] = [
    { id: 1, graph_id: 7, name: 'First', description: '', created_at: '2026-09-01T10:00:00Z' },
    { id: 2, graph_id: 7, name: 'Second', description: 'Second description', created_at: '2026-09-02T10:00:00Z' },
];

describe('VersionHistoryPanelComponent', () => {
    let fixture: ComponentFixture<VersionHistoryPanelComponent>;
    let component: VersionHistoryPanelComponent;
    let flowsApi: {
        getGraphVersions: ReturnType<typeof vi.fn>;
        deleteGraphVersion: ReturnType<typeof vi.fn>;
        updateGraphVersion: ReturnType<typeof vi.fn>;
    };
    let toast: {
        success: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
    };
    let confirmationDialog: { confirm: ReturnType<typeof vi.fn> };
    let previewed: GraphVersionDto[];
    let deleted: GraphVersionDto[];

    beforeEach(() => {
        flowsApi = {
            getGraphVersions: vi.fn().mockReturnValue(of(VERSIONS)),
            deleteGraphVersion: vi.fn().mockReturnValue(of(undefined)),
            updateGraphVersion: vi.fn(),
        };
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn() };
        confirmationDialog = { confirm: vi.fn().mockReturnValue(of(true)) };

        TestBed.configureTestingModule({
            imports: [VersionHistoryPanelComponent],
            providers: [
                { provide: FlowsApiService, useValue: flowsApi as unknown as FlowsApiService },
                {
                    provide: ConfirmationDialogService,
                    useValue: confirmationDialog as unknown as ConfirmationDialogService,
                },
                { provide: ToastService, useValue: toast as unknown as ToastService },
                { provide: Router, useValue: { navigate: vi.fn() } as unknown as Router },
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

        expect(flowsApi.deleteGraphVersion).toHaveBeenCalledWith(2);
        expect(deleted).toEqual([VERSIONS[1]]);
        expect(cards().length).toBe(1);
    });

    it('rejects a blank rename with a message instead of sending it', () => {
        component.startEdit(VERSIONS[0], 'name');
        component.editingValue = '   ';

        component.saveEdit(VERSIONS[0]);

        expect(flowsApi.updateGraphVersion).not.toHaveBeenCalled();
        expect(toast.warning).toHaveBeenCalledWith('Version name is required');
        expect(component.editingVersionId).toBeNull();
    });

    it('highlights the previewed version', () => {
        fixture.componentRef.setInput('previewedVersionId', 2);
        fixture.detectChanges();

        expect(cards()[1].classList).toContain('version-card--previewed');
        expect(cards()[0].classList).not.toContain('version-card--previewed');
    });
});
