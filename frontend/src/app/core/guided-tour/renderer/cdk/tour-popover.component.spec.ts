import { TestBed } from '@angular/core/testing';

import { TourContent } from '../../model/tour-content';
import { TourIntent, TourProgress, TourStepButtons } from '../tour-renderer';
import { TourPopoverComponent } from './tour-popover.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const CONTENT: TourContent = { title: 'Open Settings', body: ['Click the Settings icon.'] };
const ALL_BUTTONS: TourStepButtons = { next: 'Next', back: 'Back', skip: 'Skip', close: true };

interface RenderedPopover {
    readonly element: HTMLElement;
    readonly intents: TourIntent[];
    readonly component: TourPopoverComponent;
}

function renderPopover(
    content: TourContent = CONTENT,
    buttons: TourStepButtons = ALL_BUTTONS,
    progress: TourProgress | null = null,
    pending = false
): RenderedPopover {
    const fixture = TestBed.createComponent(TourPopoverComponent);
    fixture.componentRef.setInput('content', content);
    fixture.componentRef.setInput('buttons', buttons);
    fixture.componentRef.setInput('progress', progress);
    fixture.componentRef.setInput('pending', pending);
    const intents: TourIntent[] = [];
    fixture.componentInstance.intent.subscribe((intent) => intents.push(intent));
    fixture.detectChanges();
    return { element: fixture.nativeElement as HTMLElement, intents, component: fixture.componentInstance };
}

function buttonLabelled(element: HTMLElement, label: string): HTMLButtonElement {
    const button = Array.from(element.querySelectorAll('button')).find(
        (candidate) => candidate.textContent?.trim() === label || candidate.getAttribute('aria-label') === label
    );
    if (!button) {
        throw new Error(`No button labelled "${label}"`);
    }
    return button;
}

describe('TourPopoverComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('renders text runs as text, emphasising strong runs, and never parses markup in the copy', () => {
        const { element } = renderPopover({
            title: 'Save <b>now</b>',
            body: [
                'Plain <img src=x onerror=alert(1)> text',
                [{ text: 'Click ' }, { text: 'Update default models', strong: true }, { text: '.' }],
            ],
        });

        const [plain, formatted] = Array.from(element.querySelectorAll('p'));
        expect(element.querySelector('h2')?.textContent?.trim()).toBe('Save <b>now</b>');
        expect(plain.textContent?.trim()).toBe('Plain <img src=x onerror=alert(1)> text');
        expect(element.querySelector('img, b')).toBeNull();
        expect(formatted.textContent).toBe('Click Update default models.');
        expect(formatted.querySelector('strong')?.textContent).toBe('Update default models');
    });

    it('is a dialog named by its title and described by its text, and can take the focus', () => {
        const { element, component } = renderPopover();

        const dialog = element.querySelector<HTMLElement>('[role="dialog"]');
        const labelId = dialog?.getAttribute('aria-labelledby') ?? '';
        const descriptionId = dialog?.getAttribute('aria-describedby') ?? '';
        expect(element.querySelector(`[id="${labelId}"]`)?.textContent?.trim()).toBe('Open Settings');
        expect(element.querySelector(`[id="${descriptionId}"]`)?.textContent?.trim()).toBe('Click the Settings icon.');

        component.focusCard();

        expect(document.activeElement).toBe(dialog);
    });

    it.each<[string, TourIntent]>([
        ['Next', 'next'],
        ['Back', 'back'],
        ['Skip', 'skip'],
        ['Close tour', 'close'],
    ])('emits "%s" as the %s intent', (label, intent) => {
        const { element, intents } = renderPopover();

        buttonLabelled(element, label).click();

        expect(intents).toEqual([intent]);
    });

    it.each<[description: string, pending: boolean, disabledLabels: string[], emitted: TourIntent[]]>([
        [
            'disables Next and Back, keeping them focusable, while the step is pending',
            true,
            ['Back', 'Next'],
            ['skip', 'close'],
        ],
        ['disables no button while the step is live', false, [], ['back', 'skip', 'next', 'close']],
    ])('%s', (_description, pending, disabledLabels, emitted) => {
        const { element, intents } = renderPopover(CONTENT, ALL_BUTTONS, null, pending);

        const buttons = ['Back', 'Skip', 'Next', 'Close tour'].map((label) => buttonLabelled(element, label));
        buttons.forEach((button) => button.click());

        expect(
            buttons
                .filter((button) => button.getAttribute('aria-disabled') === 'true')
                .map((button) => button.getAttribute('aria-label') ?? button.textContent?.trim())
        ).toEqual(disabledLabels);
        expect(buttons.some((button) => button.disabled)).toBe(false);
        expect(intents).toEqual(emitted);
    });

    it('shows only the buttons the step asks for', () => {
        const { element } = renderPopover(CONTENT, { next: false, back: false, skip: 'Skip tour', close: false });

        const labels = Array.from(element.querySelectorAll('button')).map(
            (button) => button.getAttribute('aria-label') ?? button.textContent?.trim()
        );
        expect(labels).toEqual(['Skip tour']);
    });

    it('reports progress to assistive technology, and shows none without it', () => {
        const withProgress = renderPopover(CONTENT, ALL_BUTTONS, { current: 2, total: 4 }).element;
        const withoutProgress = renderPopover(CONTENT, ALL_BUTTONS, null).element;

        const progressBar = withProgress.querySelector('[role="progressbar"]');
        expect(progressBar?.getAttribute('aria-valuetext')).toBe('Step 2 of 4');
        expect(progressBar?.getAttribute('aria-valuenow')).toBe('2');
        expect(withoutProgress.querySelector('[role="progressbar"]')).toBeNull();
    });
});
