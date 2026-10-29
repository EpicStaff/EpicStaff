import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Venv, VenvLib } from '../../models/venv.model';
import { VenvCardComponent } from './venv-card.component';

// jsdom has no ResizeObserver; appOverflowItems only needs it to exist to start measuring.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function venvWith(libs: VenvLib[]): Venv {
    return {
        id: 7,
        name: 'ml base',
        libs,
        status: 'completed',
        error: null,
        owner: null,
        created_at: null,
        is_favorite: false,
    };
}

describe('VenvCardComponent library chips', () => {
    let fixture: ComponentFixture<VenvCardComponent>;

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

    afterEach(() => vi.unstubAllGlobals());

    function render(libs: VenvLib[]): void {
        TestBed.configureTestingModule({ imports: [VenvCardComponent] });
        fixture = TestBed.createComponent(VenvCardComponent);
        fixture.componentRef.setInput('venv', venvWith(libs));
        fixture.detectChanges();
    }

    function chip(index: number): HTMLElement {
        const chips = (fixture.nativeElement as HTMLElement).querySelectorAll(
            '.venv-card__chip:not(.venv-card__chip--overflow)'
        );
        const found = chips.item(index);
        if (!found) throw new Error(`no library chip at index ${index}`);
        return found as HTMLElement;
    }

    function text(element: HTMLElement): string {
        return (element.textContent ?? '').replace(/\s+/g, ' ').trim();
    }

    // The version is its own element so it reads differently from the name; the specifier set
    // belongs to the dialog, not the card, and must not appear here at all.
    function parts(element: HTMLElement): string[] {
        return [...element.querySelectorAll('span')].map(text).filter(Boolean);
    }

    it('shows the installed version and never the specifier set', () => {
        render([{ name: 'requests', version: '2.14.1', specification: '==2.14.1', description: null }]);

        expect(text(chip(0))).toBe('requests 2.14.1');
        expect(parts(chip(0))).toEqual(['2.14.1']);
    });

    it('shows the name alone while no version is installed', () => {
        render([{ name: 'requests', version: null, specification: '>=2.0', description: null }]);

        expect(text(chip(0))).toBe('requests');
        expect(parts(chip(0))).toEqual([]);
    });

    it('shows the installed version for a library declared without a specifier set', () => {
        render([{ name: 'requests', version: '2.14.1', specification: '', description: null }]);

        expect(text(chip(0))).toBe('requests 2.14.1');
        expect(parts(chip(0))).toEqual(['2.14.1']);
    });
});

describe('VenvCardComponent opening the venv', () => {
    function render(canEdit: boolean) {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({ imports: [VenvCardComponent] });
        const fixture = TestBed.createComponent(VenvCardComponent);
        fixture.componentRef.setInput('venv', venvWith([]));
        fixture.componentRef.setInput('canEdit', canEdit);
        const edits = vi.fn();
        fixture.componentInstance.editRequested.subscribe(edits);
        fixture.detectChanges();
        return { fixture, edits, host: fixture.nativeElement as HTMLElement };
    }

    afterEach(() => vi.unstubAllGlobals());

    it('opens the venv when the card itself is clicked', () => {
        const { edits, host } = render(true);

        host.querySelector<HTMLElement>('.venv-card')!.click();

        expect(edits).toHaveBeenCalledOnce();
    });

    it('stays shut for a user who may not edit', () => {
        const { edits, host } = render(false);

        host.querySelector<HTMLElement>('.venv-card')!.click();

        expect(edits).not.toHaveBeenCalled();
    });

    // The buttons on the card do their own thing; the card underneath must not also fire.
    it('does not open the venv when the star is clicked', () => {
        const { edits, host } = render(true);

        host.querySelector<HTMLElement>('.venv-card__icon-btn')!.click();

        expect(edits).not.toHaveBeenCalled();
    });
});
