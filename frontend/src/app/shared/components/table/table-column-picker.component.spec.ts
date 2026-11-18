import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { AppTableComponent } from './table.component';
import { AppTableColumnDef } from './table.model';
import { TableColumnPickerComponent } from './table-column-picker.component';

@Component({
    imports: [AppTableComponent, TableColumnPickerComponent],
    template: `
        <app-table-column-picker [table]="table" />
        <app-table
            #table
            layoutKey="spec-picker"
            [columns]="columns"
            [data]="[{ id: 1 }]"
        />
    `,
})
class PickerHostComponent {
    readonly columns: AppTableColumnDef[] = [
        { key: 'organization', label: 'Organization', width: '200px', pinned: 'start' },
        { key: 'admin', label: 'Admin' },
        { key: 'members', label: 'Members', hideable: false },
        { key: 'sessions', label: 'Sessions', headerGroup: 'Retention' },
        { key: 'visibility', label: 'Audit visibility', hiddenByDefault: true },
        { key: 'actions', label: 'Actions', width: '130px', pinned: 'end' },
    ];
}

describe('TableColumnPickerComponent', () => {
    // jsdom has no ResizeObserver; the item names' overflow tooltips need one.
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
    });
    afterEach(() => {
        document.querySelectorAll('.cdk-overlay-container').forEach((container) => container.remove());
        vi.unstubAllGlobals();
        localStorage.clear();
    });

    function render() {
        const fixture = TestBed.createComponent(PickerHostComponent);
        fixture.detectChanges();
        const element = fixture.nativeElement as HTMLElement;
        const trigger = element.querySelector<HTMLButtonElement>('.column-picker-trigger')!;
        const overlay = () => document.querySelector<HTMLElement>('.cdk-overlay-container');
        const open = () => {
            trigger.click();
            fixture.detectChanges();
        };
        const items = () => [...(overlay()?.querySelectorAll<HTMLElement>('.multi-select__item') ?? [])];
        const itemNames = () => items().map((item) => item.textContent?.trim());
        const checkedNames = () =>
            items()
                .filter((item) => item.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked)
                .map((item) => item.textContent?.trim());
        const clickItem = (name: string) => {
            items()
                .find((item) => item.textContent?.trim() === name)!
                .click();
            fixture.detectChanges();
        };
        const clickFooter = (label: string) => {
            [...overlay()!.querySelectorAll<HTMLButtonElement>('.multi-select__footer button')]
                .find((button) => button.textContent?.trim() === label)!
                .click();
            fixture.detectChanges();
        };
        const headerLabels = () =>
            [...element.querySelectorAll('.table-header .table-cell .col-label')].map((label) => label.textContent);
        return { trigger, overlay, open, itemNames, checkedNames, clickItem, clickFooter, headerLabels };
    }

    it('lists the hideable columns by section, with the selected / total count, leaving out the always-shown ones', () => {
        const { open, overlay, itemNames, checkedNames, trigger } = render();

        open();

        expect(trigger.getAttribute('aria-expanded')).toBe('true');
        expect(itemNames()).toEqual(['Admin', 'Audit visibility', 'Sessions']);
        expect(checkedNames()).toEqual(['Admin', 'Sessions']);
        const groupLabels = [...overlay()!.querySelectorAll('.multi-select__group-label')].map((label) =>
            label.textContent?.trim()
        );
        expect(groupLabels).toEqual(['General', 'Retention']);
        const header = overlay()!.querySelector('.multi-select__header')!;
        expect(header.textContent).toContain('Table columns view');
        expect(header.querySelector('.multi-select__header-count')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
            '2 / 3'
        );
    });

    it('applies the changes on Save only', () => {
        const { open, clickItem, clickFooter, headerLabels } = render();
        open();

        clickItem('Admin');
        clickItem('Audit visibility');
        expect(headerLabels()).toEqual(['Organization', 'Admin', 'Members', 'Sessions', 'Actions']);

        clickFooter('Save Changes');

        expect(headerLabels()).toEqual(['Organization', 'Members', 'Sessions', 'Audit visibility', 'Actions']);
    });

    it('discards the changes on Cancel', () => {
        const { open, clickItem, clickFooter, headerLabels, checkedNames } = render();
        open();

        clickItem('Admin');
        clickFooter('Cancel');

        expect(headerLabels()).toEqual(['Organization', 'Admin', 'Members', 'Sessions', 'Actions']);
        open();
        expect(checkedNames()).toEqual(['Admin', 'Sessions']);
    });

    it('ticks every column on Show All, and shows them once saved', () => {
        const { open, checkedNames, clickFooter, headerLabels } = render();
        open();

        clickFooter('Show All');
        expect(checkedNames()).toEqual(['Admin', 'Audit visibility', 'Sessions']);
        expect(headerLabels()).toEqual(['Organization', 'Admin', 'Members', 'Sessions', 'Actions']);

        clickFooter('Save Changes');

        expect(headerLabels()).toEqual(['Organization', 'Admin', 'Members', 'Sessions', 'Audit visibility', 'Actions']);
    });
});
