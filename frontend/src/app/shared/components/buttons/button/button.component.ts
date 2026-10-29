import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    inject,
    Input,
    input,
    viewChild,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

import { CollapseOnOverflowDirective } from '../../../directives/collapse-on-overflow.directive';
import { ContentTextDirective } from '../../../directives/content-text.directive';
import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-button',
    imports: [CommonModule, AppSvgIconComponent, CollapseOnOverflowDirective, ContentTextDirective, MatTooltip],
    templateUrl: './button.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./button.component.scss'],
})
export class ButtonComponent {
    @Input() type:
        | 'primary'
        | 'primary-white'
        | 'secondary'
        | 'ghost'
        | 'icon'
        | 'outline-primary'
        | 'outline-secondary'
        | 'outline-danger'
        | 'danger' = 'primary';
    @Input() mod: 'default' | 'small' = 'default';
    @Input() leftIcon?: string; // e.g., 'ui/x'
    @Input() iconSize: string = '1.1rem';
    /** Overrides `iconSize` horizontally, for icons narrower than they are tall. */
    @Input() iconWidth?: string;
    @Input() leftIconColor?: string;
    @Input() rightIcon?: string;
    @Input() rightIconColor?: string;
    readonly ariaLabel = input<string>();
    /**
     * The tooltip the button shows on hover and keyboard focus, also while disabled. Left unset it is the button's
     * name: `ariaLabel`, else the projected label text; an empty string shows none.
     */
    readonly tooltip = input<string>();
    /** The id of what describes the button (read when it gets the focus); null for none. */
    readonly ariaDescribedby = input<string | null>(null);
    disabled = input<boolean>(false);
    /**
     * Disabled like `disabled` (it looks it, and a click never reaches the host's `(click)` or the page), but it keeps
     * the focus, which `disabled` would drop: for a control that is inactive for a moment, e.g. while the focused button
     * waits for something.
     */
    readonly ariaDisabled = input<boolean>(false);

    private readonly button = viewChild.required<ElementRef<HTMLButtonElement>>('button');
    private readonly buttonTooltip = viewChild.required('button', { read: MatTooltip });
    private readonly label = viewChild(ContentTextDirective);

    private readonly labelText = computed(() => this.label()?.text() ?? '');
    protected readonly tooltipText = computed(() => this.tooltip() ?? (this.ariaLabel() || this.labelText()));
    protected readonly showsOwnTooltip = computed(() => !this.hostTooltip && !!this.tooltipText());
    /** A button without label text (an icon button) is named by its tooltip when no `ariaLabel` is given. */
    protected readonly ariaLabelAttribute = computed(
        () => this.ariaLabel() || (this.labelText() ? null : this.tooltip() || null)
    );

    public shouldCollapseToIcon = false;

    /**
     * A caller's own `matTooltip` on `<app-button>` replaces this button's tooltip; the keyboard focus of the inner
     * button shows that one, as a host element never gets the focus itself.
     */
    private readonly hostTooltip = inject(MatTooltip, { self: true, optional: true });

    public get hasAnyIcon(): boolean {
        return !!this.leftIcon || !!this.rightIcon;
    }

    public get showLeftIcon(): boolean {
        return !!this.leftIcon;
    }

    public get showRightIcon(): boolean {
        if (!this.rightIcon) return false;
        if (!this.shouldCollapseToIcon) return true;
        return !this.leftIcon;
    }

    public get collapseEnabled(): boolean {
        return this.type !== 'icon' && this.hasAnyIcon;
    }

    public onCollapseChange(collapsed: boolean): void {
        this.shouldCollapseToIcon = collapsed;
    }

    public focus(): void {
        this.button().nativeElement.focus();
    }

    protected showTooltipWhileDisabled(): void {
        this.buttonTooltip().show();
    }

    protected hideTooltipWhileDisabled(): void {
        this.buttonTooltip().hide();
    }

    protected showHostTooltipOnKeyboardFocus(): void {
        if (this.hostTooltip && this.button().nativeElement.matches(':focus-visible')) {
            this.hostTooltip.show();
        }
    }

    protected hideHostTooltip(): void {
        this.hostTooltip?.hide();
    }

    /** Ends a click (mouse, Enter or Space) on the inner button here while aria-disabled, as a disabled button would. */
    protected stopClickWhileAriaDisabled(event: Event): void {
        if (this.ariaDisabled()) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }
}
