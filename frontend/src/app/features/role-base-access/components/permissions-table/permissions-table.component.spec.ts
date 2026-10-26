import { OutputEmitterRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { CatalogResponse } from '@shared/models';

import { PermissionsTableComponent } from './permissions-table.component';

const CATALOG = {
    actions: [
        { code: 'read', label: 'Read', bit: 1 },
        { code: 'update', label: 'Update', bit: 2 },
    ],
    resource_types: [
        {
            code: 'flows',
            label: 'Flows',
            group: 'core',
            description: '',
            applicable_actions: ['read', 'update'],
            platform_actions: [],
            recommended_with: {},
        },
        {
            code: 'tools',
            label: 'Tools',
            group: 'core',
            description: '',
            applicable_actions: ['read', 'update'],
            platform_actions: [],
            recommended_with: {},
        },
    ],
} as unknown as CatalogResponse;

// One of the two resources has Read: the group, the Read column and the Flows row all show "-".
const PARTIAL_SELECTION = ['flows:read'];

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

type ToggleOutput = 'groupToggle' | 'groupActionToggle' | 'resourceToggle';

const TRI_STATE_BOXES: [string, string, ToggleOutput][] = [
    ['group bulk select', '.resource-row.bulk > app-checkbox input', 'groupToggle'],
    ['group action bulk select', '.resource-row.bulk .action-cell input', 'groupActionToggle'],
    ['resource row', '.row-select input', 'resourceToggle'],
];

function clickBox(selector: string, selected: string[], output: ToggleOutput) {
    const fixture = TestBed.createComponent(PermissionsTableComponent);
    fixture.componentRef.setInput('catalog', CATALOG);
    fixture.componentRef.setInput('selectedPermissions', new Set(selected));
    fixture.detectChanges();

    const emitted: { select: boolean }[] = [];
    (fixture.componentInstance[output] as OutputEmitterRef<{ select: boolean }>).subscribe((event) =>
        emitted.push(event)
    );
    const box = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(selector)!;
    box.click();

    return { select: emitted[0].select, boxTicked: box.checked };
}

describe('PermissionsTableComponent tri-state checkboxes', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it.each(TRI_STATE_BOXES)('an empty %s selects everything', (_name, selector, output) => {
        expect(clickBox(selector, [], output)).toEqual({ select: true, boxTicked: true });
    });

    it.each(TRI_STATE_BOXES)('a "-" %s clears the selection and leaves the box unticked', (_name, selector, output) => {
        expect(clickBox(selector, PARTIAL_SELECTION, output)).toEqual({ select: false, boxTicked: false });
    });
});
