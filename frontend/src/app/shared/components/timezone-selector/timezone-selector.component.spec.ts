import { ComponentFixture, TestBed } from '@angular/core/testing';

import { normalizeIana, TimezoneSelectorComponent } from './timezone-selector.component';

describe('normalizeIana', () => {
    it('maps the legacy Kiev name to Kyiv', () => {
        expect(normalizeIana('Europe/Kiev')).toBe('Europe/Kyiv');
    });

    it('keeps any other zone unchanged', () => {
        expect(normalizeIana('Europe/Kyiv')).toBe('Europe/Kyiv');
        expect(normalizeIana('America/New_York')).toBe('America/New_York');
    });
});

describe('TimezoneSelectorComponent keyboard', () => {
    function mount(value: string) {
        const fixture = TestBed.createComponent(TimezoneSelectorComponent);
        fixture.detectChanges();
        fixture.componentInstance.writeValue(value);
        const picked: string[] = [];
        fixture.componentInstance.registerOnChange((iana) => picked.push(iana));
        document.body.appendChild(fixture.nativeElement);
        return { fixture, picked };
    }

    function trigger(fixture: ComponentFixture<TimezoneSelectorComponent>): HTMLButtonElement {
        return fixture.nativeElement.querySelector('.tz-selector__btn');
    }

    function search(): HTMLInputElement {
        return document.querySelector<HTMLInputElement>('.tz-selector__search')!;
    }

    function highlighted(): string | undefined {
        return document.querySelector('.tz-selector__option--active .tz-selector__iana')?.textContent?.trim();
    }

    function press(target: HTMLElement, key: string): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { key, code: key, bubbles: true, cancelable: true });
        target.dispatchEvent(event);
        return event;
    }

    function open(fixture: ComponentFixture<TimezoneSelectorComponent>): void {
        vi.useFakeTimers();
        trigger(fixture).click();
        fixture.detectChanges();
        vi.advanceTimersByTime(50);
        fixture.detectChanges();
    }

    function type(fixture: ComponentFixture<TimezoneSelectorComponent>, text: string): void {
        search().value = text;
        search().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    afterEach(() => {
        vi.useRealTimers();
        document
            .querySelectorAll('app-timezone-selector, .cdk-overlay-container')
            .forEach((element) => element.remove());
    });

    it('opens with focus in the search field and the current timezone highlighted', () => {
        const { fixture } = mount('Europe/Kyiv');
        expect(trigger(fixture).getAttribute('aria-haspopup')).toBe('listbox');
        expect(trigger(fixture).getAttribute('aria-expanded')).toBe('false');

        open(fixture);

        expect(document.activeElement).toBe(search());
        expect(highlighted()).toBe('Europe/Kyiv');
        expect(trigger(fixture).getAttribute('aria-expanded')).toBe('true');
    });

    it('moves the highlight with the arrows and picks it on Enter, back on the button', () => {
        const { fixture, picked } = mount('Europe/Kyiv');
        open(fixture);
        const options = fixture.componentInstance.filteredOptions();
        const kyivIndex = options.findIndex((tz) => tz.iana === 'Europe/Kyiv');

        const down = press(search(), 'ArrowDown');
        fixture.detectChanges();
        expect(highlighted()).toBe(options[kyivIndex + 1].iana);
        expect(down.defaultPrevented).toBe(true);

        press(search(), 'Enter');
        fixture.detectChanges();

        expect(picked).toEqual([options[kyivIndex + 1].iana]);
        expect(fixture.componentInstance.open()).toBe(false);
        expect(document.activeElement).toBe(trigger(fixture));
    });

    it('highlights the first match while typing, so Enter takes it', () => {
        const { fixture, picked } = mount('Europe/Kyiv');
        open(fixture);

        type(fixture, 'tokyo');
        press(search(), 'Enter');

        expect(picked).toEqual(['Asia/Tokyo']);
    });

    it('does nothing on Enter when nothing matches', () => {
        const { fixture, picked } = mount('Europe/Kyiv');
        open(fixture);

        type(fixture, 'no such zone');
        press(search(), 'Enter');

        expect(picked).toEqual([]);
        expect(fixture.componentInstance.open()).toBe(true);
    });

    it('closes only the list on Esc, leaving the panel or dialog under it open', () => {
        const { fixture, picked } = mount('Europe/Kyiv');
        open(fixture);
        // The flow editor's Esc (close the side panel) listens on the window.
        const windowEscape = vi.fn();
        window.addEventListener('keydown', windowEscape);

        press(search(), 'Escape');
        fixture.detectChanges();
        window.removeEventListener('keydown', windowEscape);

        expect(fixture.componentInstance.open()).toBe(false);
        expect(windowEscape).not.toHaveBeenCalled();
        expect(picked).toEqual([]);
        expect(document.activeElement).toBe(trigger(fixture));
    });
});
