import { OverlayContainer } from '@angular/cdk/overlay';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LabelColor } from '@shared/models';

import { LabelColorPickerComponent } from './label-color-picker.component';

// The CDK reads `keyCode` (arrow keys, Escape), which a synthetic KeyboardEvent leaves at 0.
const KEY_CODES: Record<string, number> = { ArrowDown: 40, ArrowUp: 38, Enter: 13, Escape: 27, ' ': 32 };

function press(key: string): void {
    const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
    Object.defineProperty(event, 'keyCode', { get: () => KEY_CODES[key] ?? 0 });
    (document.activeElement ?? document.body).dispatchEvent(event);
}

function openPicker(selectedColor: LabelColor): {
    fixture: ComponentFixture<LabelColorPickerComponent>;
    trigger: HTMLButtonElement;
    panelOpen: () => boolean;
    picked: LabelColor[];
} {
    const fixture = TestBed.createComponent(LabelColorPickerComponent);
    const picked: LabelColor[] = [];
    fixture.componentInstance.colorChange.subscribe((color) => picked.push(color));
    fixture.componentRef.setInput('selectedColor', selectedColor);
    fixture.detectChanges();
    const trigger = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.color-trigger-btn')!;
    trigger.focus();
    trigger.click();
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, trigger, panelOpen: () => overlay.querySelector('[role="listbox"]') !== null, picked };
}

const focusedColor = (): string | null => document.activeElement?.getAttribute('aria-label') ?? null;

describe('LabelColorPickerComponent keyboard', () => {
    it('moves focus into the panel, onto the selected color, when it opens', () => {
        openPicker(LabelColor.Blue);

        expect(focusedColor()).toBe(LabelColor.Blue);
    });

    it.each([
        { keys: ['ArrowDown'], focused: LabelColor.Green },
        { keys: ['ArrowUp'], focused: LabelColor.Purple },
        { keys: ['ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowDown'], focused: LabelColor.Default },
    ])('from the selected color, $keys moves focus to $focused', ({ keys, focused }) => {
        openPicker(LabelColor.Blue);

        for (const key of keys) press(key);

        expect(focusedColor()).toBe(focused);
    });

    it.each(['Enter', ' '])(
        '"%s" picks the focused color, closes the panel and returns focus to the trigger',
        (key) => {
            const { fixture, trigger, panelOpen, picked } = openPicker(LabelColor.Blue);

            press('ArrowDown');
            press(key);
            fixture.detectChanges();

            expect(picked).toEqual([LabelColor.Green]);
            expect(panelOpen()).toBe(false);
            expect(document.activeElement).toBe(trigger);
        }
    );

    it('Escape closes the panel without picking and returns focus to the trigger', () => {
        const { fixture, trigger, panelOpen, picked } = openPicker(LabelColor.Blue);

        press('ArrowDown');
        press('Escape');
        fixture.detectChanges();

        expect(picked).toEqual([]);
        expect(panelOpen()).toBe(false);
        expect(document.activeElement).toBe(trigger);
    });
});
