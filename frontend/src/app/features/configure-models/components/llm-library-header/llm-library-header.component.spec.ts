import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { LlmLibraryHeaderComponent } from './llm-library-header.component';

describe('LlmLibraryHeaderComponent toolbar layout', () => {
    /** Observers that report a header width on demand; the toolbar controls' own observers are left alone. */
    const headerObservers: { callback: ResizeObserverCallback; element: Element }[] = [];

    class MeasuringResizeObserver {
        constructor(private readonly callback: ResizeObserverCallback) {}
        observe(element: Element): void {
            if (element.tagName === 'HEADER') headerObservers.push({ callback: this.callback, element });
        }
        unobserve(): void {}
        disconnect(): void {}
    }

    beforeEach(() => {
        headerObservers.length = 0;
        vi.stubGlobal('ResizeObserver', MeasuringResizeObserver);
    });
    afterEach(() => vi.unstubAllGlobals());

    /** The header as the page shows it with configs to select, for a user who may create and delete them. */
    function render(withSelection: boolean): ComponentFixture<LlmLibraryHeaderComponent> {
        const grantedActions = [ActionCode.Create, ActionCode.Delete];
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (_resource: ResourceCode, action: ActionCode) => grantedActions.includes(action),
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(LlmLibraryHeaderComponent);
        fixture.componentRef.setInput('showSelect', true);
        fixture.componentRef.setInput('selectMode', withSelection);
        fixture.componentRef.setInput('selectedCount', withSelection ? 1 : 0);
        fixture.detectChanges();
        return fixture;
    }

    function setHeaderWidth(fixture: ComponentFixture<LlmLibraryHeaderComponent>, width: number): void {
        for (const { callback, element } of headerObservers) {
            callback([{ target: element, contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver);
        }
        fixture.detectChanges();
    }

    /** Where the toolbar is, and which of its controls show only icons (Select's look stands for Capabilities'). */
    function layoutOf(fixture: ComponentFixture<LlmLibraryHeaderComponent>): string {
        const element = fixture.nativeElement as HTMLElement;
        const stacked = !!element.querySelector('.header--stacked');
        const selectIcon = !!element.querySelector('.bulk-select--icon-only');
        const actionIcon = !!element.querySelector('.header-right > app-button .btn--icon-only');
        if (!stacked) return selectIcon && actionIcon ? 'icons' : 'labels';
        if (selectIcon) return 'stacked-icons';
        return actionIcon ? 'stacked-action-icon' : 'stacked';
    }

    // The controls are not measured here (no layout in jsdom): the switches come from the estimated widths.
    it.each([
        [false, 1054, 'labels'],
        [false, 1053, 'icons'],
        [false, 768, 'icons'],
        [false, 767, 'stacked'],
        [false, 449, 'stacked'],
        [false, 448, 'stacked-action-icon'],
        [false, 309, 'stacked-action-icon'],
        [false, 308, 'stacked-icons'],
        [true, 1075, 'labels'],
        [true, 1074, 'icons'],
        [true, 859, 'icons'],
        [true, 858, 'stacked'],
        [true, 470, 'stacked'],
        [true, 469, 'stacked-action-icon'],
        [true, 390, 'stacked-action-icon'],
        [true, 389, 'stacked-icons'],
    ])('with a selection: %s, at a %spx header lays the toolbar out as %s', (withSelection, width, layout) => {
        const fixture = render(withSelection);
        // Flushes the effect that starts observing the header once it is rendered.
        TestBed.tick();

        setHeaderWidth(fixture, width);

        expect(layoutOf(fixture)).toBe(layout);
    });
});
