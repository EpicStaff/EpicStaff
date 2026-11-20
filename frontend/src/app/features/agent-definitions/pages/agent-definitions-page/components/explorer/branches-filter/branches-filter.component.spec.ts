import { TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { ExplorerSectionId } from '../../../../../models/explorer.model';
import { BranchesFilterComponent } from './branches-filter.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function render(readable: ResourceCode[], selected: ExplorerSectionId[]) {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PermissionsService,
                useValue: {
                    can: (resource: ResourceCode, action: ActionCode) =>
                        action === ActionCode.Read && readable.includes(resource),
                },
            },
        ],
    });
    const fixture = TestBed.createComponent(BranchesFilterComponent);
    fixture.componentRef.setInput('selected', new Set(selected));
    const saved: Set<ExplorerSectionId>[] = [];
    fixture.componentInstance.save.subscribe((ids) => saved.push(ids));
    fixture.detectChanges();
    const host = fixture.nativeElement as HTMLElement;
    const rows = () =>
        Array.from(host.querySelectorAll<HTMLElement>('.filter__item')).map((row) => ({
            label: row.querySelector('.filter__label')?.textContent?.trim(),
            locked: row.getAttribute('aria-disabled') === 'true',
        }));
    return { fixture, rows, saved };
}

describe('BranchesFilterComponent', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('lists Agents as the always-shown row for a role that reads agents', () => {
        const { rows } = render(
            [ResourceCode.Agents, ResourceCode.Surfaces, ResourceCode.Files],
            ['agents', 'surfaces', 'storage']
        );

        expect(rows()).toEqual([
            { label: 'Agent', locked: true },
            { label: 'Shared Surfaces', locked: false },
            { label: 'Storage', locked: false },
        ]);
    });

    it('hides Agents and locks Shared Surfaces for a role that reads surfaces only', () => {
        const { rows } = render([ResourceCode.Surfaces], ['surfaces']);

        expect(rows()).toEqual([{ label: 'Shared Surfaces', locked: true }]);
    });

    it('keeps Shared Surfaces when Clear Filter is saved by that role', () => {
        const { fixture, saved } = render([ResourceCode.Surfaces, ResourceCode.Files], ['surfaces', 'storage']);

        fixture.componentInstance.onClearFilter();
        fixture.componentInstance.onSave();

        expect([...saved[0]]).toEqual(['surfaces']);
    });
});
