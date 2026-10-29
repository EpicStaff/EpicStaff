import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    signal,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';

import { nextListIndex } from '../../utils/list-navigation.util';

interface TimezoneOption {
    iana: string;
    offsetLabel: string;
    displayLabel: string;
    searchText: string;
}

function getUtcOffsetLabel(iana: string): string {
    try {
        const parts = new Intl.DateTimeFormat('en', {
            timeZone: iana,
            timeZoneName: 'shortOffset',
        }).formatToParts(new Date());
        const raw = parts.find((p) => p.type === 'timeZoneName')?.value ?? 'GMT';
        if (raw === 'GMT') return 'UTC+00:00';
        const withUTC = raw.replace('GMT', 'UTC');
        // Pad single-digit hours: UTC+3 → UTC+03:00, UTC+5:30 → UTC+05:30
        return withUTC.replace(
            /UTC([+-])(\d)(:(\d{2}))?$/,
            (_m, sign: string, h: string, _c: string, min: string) => `UTC${sign}0${h}:${min ?? '00'}`
        );
    } catch {
        return 'UTC+00:00';
    }
}

const IANA_ALIASES: Record<string, string> = {
    'Europe/Kiev': 'Europe/Kyiv',
};

export function normalizeIana(iana: string): string {
    return IANA_ALIASES[iana] ?? iana;
}

function buildTimezoneOptions(): TimezoneOption[] {
    let zones: string[];
    try {
        zones = Intl.supportedValuesOf('timeZone');
    } catch {
        zones = [
            'UTC',
            'America/New_York',
            'America/Los_Angeles',
            'Europe/London',
            'Europe/Paris',
            'Europe/Kyiv',
            'Asia/Tokyo',
            'Asia/Shanghai',
            'Australia/Sydney',
        ];
    }

    const seen = new Set<string>();
    const options: TimezoneOption[] = [];

    for (const raw of zones) {
        const iana = normalizeIana(raw);
        if (seen.has(iana)) continue;
        seen.add(iana);

        const offsetLabel = getUtcOffsetLabel(iana);
        // Include legacy aliases in searchText so both spellings match.
        const aliases = Object.entries(IANA_ALIASES)
            .filter(([, canonical]) => canonical === iana)
            .map(([alias]) => alias.toLowerCase());
        const searchText = [`${iana} ${offsetLabel}`.toLowerCase(), ...aliases].join(' ');

        options.push({ iana, offsetLabel, displayLabel: `${iana} · ${offsetLabel}`, searchText });
    }

    return options;
}

const ALL_TIMEZONE_OPTIONS: TimezoneOption[] = buildTimezoneOptions();

let nextSelectorId = 0;

@Component({
    selector: 'app-timezone-selector',
    imports: [OverlayModule, FormsModule],
    templateUrl: './timezone-selector.component.html',
    styleUrls: ['./timezone-selector.component.scss'],
    providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: TimezoneSelectorComponent, multi: true }],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimezoneSelectorComponent implements ControlValueAccessor {
    /** Readonly mode: renders the current timezone as plain text (no dropdown). */
    readonly = input<boolean>(false);

    open = signal(false);
    isDisabled = signal(false);
    selectedValue = signal<string | null>(null);
    searchQuery = signal('');
    /** The option the arrow keys point at in the open list, or -1; Enter picks it. */
    readonly activeIndex = signal(-1);
    protected readonly listId = `tz-selector-list-${nextSelectorId++}`;

    readonly allOptions = ALL_TIMEZONE_OPTIONS;

    filteredOptions = computed(() => {
        const q = this.searchQuery().toLowerCase().trim();
        if (!q) return this.allOptions;
        return this.allOptions.filter((tz) => tz.searchText.includes(q));
    });

    selectedOption = computed(() => this.allOptions.find((tz) => tz.iana === this.selectedValue()) ?? null);

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: TemplateRef<unknown>;
    @ViewChild('searchInput') searchInput!: ElementRef<HTMLInputElement>;

    private overlayRef!: OverlayRef;
    private readonly overlay = inject(Overlay);
    private readonly overlayPositionBuilder = inject(OverlayPositionBuilder);
    private readonly vcr = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);

    private onChange: (value: string) => void = () => {};
    private onTouched: () => void = () => {};

    toggle(): void {
        if (this.readonly()) return;
        this.open() ? this.close() : this.openDropdown();
    }

    openDropdown(): void {
        if (this.readonly()) return;
        if (!this.overlayRef) {
            const positionStrategy = this.overlayPositionBuilder
                .flexibleConnectedTo(this.triggerBtn)
                .withPositions([
                    { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                    { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
                ])
                .withPush(false);

            this.overlayRef = this.overlay.create({
                positionStrategy,
                scrollStrategy: this.overlay.scrollStrategies.reposition(),
                hasBackdrop: true,
                backdropClass: 'transparent-backdrop',
                width: this.triggerBtn.nativeElement.offsetWidth,
            });

            this.overlayRef
                .backdropClick()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(() => this.close());

            // Listening here makes this list, not a dialog under it, the one Esc closes. Stopping the key keeps it from
            // window-level handlers too, such as the flow editor's Esc that would close the node side panel.
            this.overlayRef
                .keydownEvents()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((event) => {
                    if (event.key === 'Escape') {
                        event.preventDefault();
                        event.stopPropagation();
                        this.close();
                    }
                });
        }

        // Sync width on every open so the dropdown matches the trigger
        // even if the panel was resized since the overlay was first created.
        this.overlayRef.updateSize({ width: this.triggerBtn.nativeElement.offsetWidth });

        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.open.set(true);
        this.searchQuery.set('');
        // The list opens on the current timezone, so the arrows start from it.
        this.activeIndex.set(this.filteredOptions().findIndex((tz) => tz.iana === this.selectedValue()));
        setTimeout(() => {
            this.searchInput?.nativeElement?.focus();
            this.scrollToActive();
        }, 50);
    }

    close(): void {
        const wasOpen = this.open();
        if (this.overlayRef) {
            this.overlayRef.detach();
        }
        this.onTouched();
        this.open.set(false);
        // Back on the button, so Tab goes on from there.
        if (wasOpen) this.triggerBtn?.nativeElement.focus();
    }

    protected optionId(index: number): string {
        return `${this.listId}-${index}`;
    }

    // Typing highlights the first match, so Enter takes it.
    protected onSearchChange(query: string): void {
        this.searchQuery.set(query);
        this.activeIndex.set(this.filteredOptions().length > 0 ? 0 : -1);
        this.scrollToActive();
    }

    // Focus stays in the search field; the arrows move the highlight and Enter picks it. Home and End stay with the caret.
    protected onSearchKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            const option = this.filteredOptions()[this.activeIndex()];
            if (option) {
                event.preventDefault();
                this.onSelect(option);
            }
            return;
        }
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        const next = nextListIndex(event.key, this.activeIndex(), this.filteredOptions().length);
        if (next === null) return;
        event.preventDefault();
        this.activeIndex.set(next);
        this.scrollToActive();
    }

    private scrollToActive(): void {
        const index = this.activeIndex();
        if (index < 0) return;
        this.overlayRef?.overlayElement
            .querySelector(`#${CSS.escape(this.optionId(index))}`)
            ?.scrollIntoView?.({ block: 'nearest' });
    }

    onSelect(tz: TimezoneOption): void {
        if (this.readonly()) return;
        this.selectedValue.set(tz.iana);
        this.onChange(tz.iana);
        this.onTouched();
        this.close();
    }

    writeValue(value: string): void {
        this.selectedValue.set(value ?? null);
    }

    registerOnChange(fn: (value: string) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
