import type { DriverHook, DriveStep } from 'driver.js';

import { TourTopLayer, withTopLayer } from './tour-top-layer';

type HookOptions = Parameters<DriverHook>[2];

describe('TourTopLayer', () => {
    // Before and after: other spec files share this jsdom document.
    const removeTourElements = (): void => {
        document.body
            .querySelectorAll('.driver-overlay, .driver-popover, .quickstart-tour-layer')
            .forEach((element) => {
                element.remove();
            });
    };
    beforeEach(removeTourElements);
    afterEach(removeTourElements);

    function appendToBody(className: string): HTMLElement {
        const element = document.createElement('div');
        element.className = className;
        document.body.appendChild(element);
        return element;
    }

    it('moves the driver.js overlay and popover from <body> into a manual popover host', () => {
        const overlay = appendToBody('driver-overlay');
        const popover = appendToBody('driver-popover');
        const layer = new TourTopLayer(document);

        layer.raise();

        const host = document.querySelector('.quickstart-tour-layer');
        expect(host?.getAttribute('popover')).toBe('manual');
        expect(overlay.parentElement).toBe(host);
        expect(popover.parentElement).toBe(host);
    });

    it('reuses one host and picks up a popover re-created for the next step', () => {
        const layer = new TourTopLayer(document);
        appendToBody('driver-popover');
        layer.raise();

        const nextPopover = appendToBody('driver-popover');
        layer.raise();

        expect(document.querySelectorAll('.quickstart-tour-layer')).toHaveLength(1);
        expect(nextPopover.parentElement?.classList.contains('quickstart-tour-layer')).toBe(true);
    });

    it('removes the host on dispose, and dispose is idempotent', () => {
        const layer = new TourTopLayer(document);
        layer.raise();

        layer.dispose();
        layer.dispose();

        expect(document.querySelector('.quickstart-tour-layer')).toBeNull();
    });

    it('raises the layer from every step hook and still runs the step’s own hooks', () => {
        const layer = new TourTopLayer(document);
        const raise = vi.spyOn(layer, 'raise');
        const ownHighlighted = vi.fn();
        const ownPopoverRender = vi.fn();
        const [step] = withTopLayer(
            [{ onHighlighted: ownHighlighted, popover: { onPopoverRender: ownPopoverRender } } as DriveStep],
            layer
        );
        const options = {} as HookOptions;

        step.onHighlightStarted?.(undefined, step, options);
        step.onHighlighted?.(undefined, step, options);
        step.popover?.onPopoverRender?.({} as never, options);

        expect(raise).toHaveBeenCalledTimes(3);
        expect(ownHighlighted).toHaveBeenCalled();
        expect(ownPopoverRender).toHaveBeenCalled();
    });

    it('mounts appended elements in the host and removes them with it', () => {
        const layer = new TourTopLayer(document);
        const canvas = document.createElement('canvas');

        layer.append(canvas);
        expect(canvas.parentElement?.classList.contains('quickstart-tour-layer')).toBe(true);

        layer.dispose();
        expect(canvas.isConnected).toBe(false);
    });

    it('stays gone after dispose: late raise() or append() does not re-create the host', () => {
        const layer = new TourTopLayer(document);
        layer.raise();
        layer.dispose();

        layer.raise();
        layer.append(document.createElement('canvas'));

        expect(document.querySelector('.quickstart-tour-layer')).toBeNull();
    });

    // jsdom has no Popover API; stub just enough of it to exercise the hide/show re-raise and the focus restore.
    describe('with the Popover API', () => {
        const openPopovers = new Set<Element>();
        const originalMatches = Element.prototype.matches;
        const popoverMethods = ['showPopover', 'hidePopover'] as const;
        const originalDescriptors = popoverMethods.map((name) =>
            Object.getOwnPropertyDescriptor(HTMLElement.prototype, name)
        );
        const showPopover = vi.fn(function (this: HTMLElement) {
            openPopovers.add(this);
        });
        const hidePopover = vi.fn(function (this: HTMLElement) {
            openPopovers.delete(this);
            // Browsers move focus out of a popover that is hidden.
            const focused = document.activeElement;
            if (focused instanceof HTMLElement && this.contains(focused)) {
                focused.blur();
            }
        });

        beforeEach(() => {
            showPopover.mockClear();
            hidePopover.mockClear();
            Object.defineProperty(HTMLElement.prototype, 'showPopover', { value: showPopover, configurable: true });
            Object.defineProperty(HTMLElement.prototype, 'hidePopover', { value: hidePopover, configurable: true });
            vi.spyOn(Element.prototype, 'matches').mockImplementation(function (this: Element, selector: string) {
                return selector === ':popover-open' ? openPopovers.has(this) : originalMatches.call(this, selector);
            });
        });

        afterEach(() => {
            popoverMethods.forEach((name, index) => {
                const original = originalDescriptors[index];
                if (original) {
                    Object.defineProperty(HTMLElement.prototype, name, original);
                } else {
                    delete (HTMLElement.prototype as Partial<HTMLElement>)[name];
                }
            });
            vi.restoreAllMocks();
            openPopovers.clear();
        });

        it('shows the host, then hides and re-shows it on each raise so it is the newest top-layer entry', () => {
            const layer = new TourTopLayer(document);

            layer.raise();
            layer.raise();

            expect(showPopover).toHaveBeenCalledTimes(2);
            expect(hidePopover).toHaveBeenCalledTimes(1);
            expect(hidePopover.mock.invocationCallOrder[0]).toBeLessThan(showPopover.mock.invocationCallOrder[1]);
        });

        it('keeps focus on the popover button across a re-raise', () => {
            const popover = appendToBody('driver-popover');
            const button = document.createElement('button');
            popover.appendChild(button);
            const layer = new TourTopLayer(document);
            layer.raise();
            button.focus();

            layer.raise();

            expect(document.activeElement).toBe(button);
        });

        it('hides the host before removing it on dispose', () => {
            const layer = new TourTopLayer(document);
            layer.raise();

            layer.dispose();

            expect(hidePopover).toHaveBeenCalledTimes(1);
            expect(openPopovers.size).toBe(0);
        });
    });
});
