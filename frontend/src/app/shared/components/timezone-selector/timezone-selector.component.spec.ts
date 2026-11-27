import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TimezoneSelectorComponent } from './timezone-selector.component';

describe('TimezoneSelectorComponent keyboard', () => {
    function mount(value: string | null, offerBrowserZone?: boolean, offerDefaultZone?: string) {
        const fixture = TestBed.createComponent(TimezoneSelectorComponent);
        if (offerBrowserZone !== undefined) fixture.componentRef.setInput('offerBrowserZone', offerBrowserZone);
        if (offerDefaultZone !== undefined) fixture.componentRef.setInput('offerDefaultZone', offerDefaultZone);
        fixture.detectChanges();
        fixture.componentInstance.writeValue(value);
        fixture.detectChanges();
        const picked: (string | null)[] = [];
        fixture.componentInstance.registerOnChange((zone) => picked.push(zone));
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
        const kyivIndex = options.findIndex((tz) => tz.value === 'Europe/Kyiv');

        const down = press(search(), 'ArrowDown');
        fixture.detectChanges();
        expect(highlighted()).toBe(options[kyivIndex + 1].label);
        expect(down.defaultPrevented).toBe(true);

        press(search(), 'Enter');
        fixture.detectChanges();

        expect(picked).toEqual([options[kyivIndex + 1].value]);
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

    describe('browser timezone option', () => {
        const optionLabels = (): string[] =>
            Array.from(document.querySelectorAll('.tz-selector__option .tz-selector__iana')).map(
                (label) => label.textContent?.trim() ?? ''
            );
        const shown = (fixture: ComponentFixture<TimezoneSelectorComponent>): string =>
            fixture.nativeElement.querySelector('.tz-selector__text').textContent.trim();

        beforeEach(() => {
            vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
                timeZone: 'Asia/Tokyo',
            } as Intl.ResolvedDateTimeFormatOptions);
        });

        afterEach(() => vi.restoreAllMocks());

        it('is left out without the input: an empty value shows the placeholder, and the list holds zones only', () => {
            const { fixture } = mount(null);
            expect(shown(fixture)).toBe('Select timezone');
            expect(trigger(fixture).classList).toContain('tz-selector__btn--placeholder');

            open(fixture);

            expect(optionLabels().some((label) => label.startsWith('Use browser timezone'))).toBe(false);
            expect(highlighted()).toBeUndefined();
        });

        it('comes first with the input, and picking it writes null', () => {
            const { fixture, picked } = mount('Europe/Kyiv', true);
            open(fixture);

            expect(optionLabels()[0]).toBe('Use browser timezone (Asia/Tokyo)');
            document.querySelector<HTMLElement>('.tz-selector__option')!.click();
            fixture.detectChanges();

            expect(picked).toEqual([null]);
            expect(shown(fixture)).toBe('Use browser timezone (Asia/Tokyo)');
        });

        it('shows an empty value as the browser option picked, not as the placeholder', () => {
            const { fixture } = mount(null, true);

            expect(shown(fixture)).toBe('Use browser timezone (Asia/Tokyo)');
            expect(trigger(fixture).classList).not.toContain('tz-selector__btn--placeholder');
            open(fixture);
            expect(highlighted()).toBe('Use browser timezone (Asia/Tokyo)');
        });
    });

    describe('default timezone option', () => {
        const optionLabels = (): string[] =>
            Array.from(document.querySelectorAll('.tz-selector__option .tz-selector__iana')).map(
                (label) => label.textContent?.trim() ?? ''
            );
        const shown = (fixture: ComponentFixture<TimezoneSelectorComponent>): string =>
            fixture.nativeElement.querySelector('.tz-selector__text').textContent.trim();

        it('comes first with the input, shows an empty value as picked, and picking it writes null', () => {
            const { fixture, picked } = mount('Asia/Tokyo', undefined, 'Europe/Kyiv');
            open(fixture);

            expect(optionLabels()[0]).toBe('Use my default (Europe/Kyiv)');
            document.querySelector<HTMLElement>('.tz-selector__option')!.click();
            fixture.detectChanges();

            expect(picked).toEqual([null]);
            expect(shown(fixture)).toBe('Use my default (Europe/Kyiv)');
        });

        it('takes the place of the browser option when both are asked for', () => {
            const { fixture } = mount(null, true, 'Europe/Kyiv');
            open(fixture);

            expect(optionLabels()[0]).toBe('Use my default (Europe/Kyiv)');
            expect(optionLabels().some((label) => label.startsWith('Use browser timezone'))).toBe(false);
        });
    });
});
