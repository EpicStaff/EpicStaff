import { CommonModule } from '@angular/common';
import {
    AfterViewInit,
    Component,
    ElementRef,
    EventEmitter,
    forwardRef,
    Input,
    Output,
    ViewChild,
} from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';

import { HelpTooltipComponent } from '../help-tooltip/help-tooltip.component';

@Component({
    selector: 'app-custom-input',
    standalone: true,
    imports: [CommonModule, FormsModule, HelpTooltipComponent, MatTooltipModule],
    template: `
        <div class="form-group">
            @if (label) {
                <div class="label-container">
                    <label [for]="id">{{ label }}</label>
                    @if (required) {
                        <span class="required">*</span>
                    }
                    @if (tooltipText) {
                        <app-help-tooltip
                            [text]="tooltipText"
                            position="right"
                            [icon]="isClassIcon ? 'help' : icon"
                            [iconClass]="isClassIcon ? icon : ''"
                            size="18px"
                        />
                    }
                </div>
            }
            <div class="input-wrapper">
                <input
                    #inputEl
                    [type]="effectiveType"
                    [id]="id"
                    [name]="name"
                    [attr.autocomplete]="effectiveAutocomplete"
                    [placeholder]="placeholder"
                    [(ngModel)]="value"
                    (blur)="onTouched(); blur.emit()"
                    class="text-input"
                    [class.has-toggle]="hasToggle"
                    [class.masked]="isMasked"
                    [class.error]="errorMessage"
                    [disabled]="isDisabled"
                    [style.--active-color]="activeColor"
                />
                @if (hasToggle) {
                    <button
                        type="button"
                        class="toggle-visibility"
                        [matTooltip]="passwordVisible ? 'Hide' : 'Show'"
                        matTooltipPosition="above"
                        (click)="togglePasswordVisibility()"
                        tabindex="-1"
                    >
                        <i [class]="'ti ' + (passwordVisible ? 'ti-eye' : 'ti-eye-off')"></i>
                    </button>
                }
            </div>
            @if (errorMessage) {
                <div class="error-message">
                    {{ errorMessage }}
                </div>
            }
        </div>
    `,
    styles: [
        `
            :host {
                width: 100%;
            }

            .form-group {
                .label-container {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    margin-bottom: 8px;

                    .required {
                        color: var(--color-required-asterisk, var(--accent-color));
                    }
                }

                label {
                    display: block;
                    font-size: var(--font-size-md);
                    line-height: 130%;
                    color: var(--color-text-primary);
                    margin: 0;
                }

                .input-wrapper {
                    position: relative;
                    display: flex;
                    align-items: center;
                }

                .text-input {
                    width: 100%;
                    padding: 8px 12px;

                    &::-ms-reveal {
                        display: none;
                    }
                    background-color: var(--color-input-background);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 6px;
                    color: var(--color-text-primary);
                    font-size: var(--font-size-md);
                    transition: border-color 0.2s ease;

                    &::placeholder {
                        color: var(--color-input-text-placeholder);
                    }

                    &.masked {
                        -webkit-text-security: disc;
                    }

                    &.has-toggle {
                        padding-right: 36px;
                    }

                    &:focus {
                        outline: none;
                        border-color: var(--active-color, #685fff);
                    }

                    &.error {
                        border-color: #ef4444;
                    }
                }

                .toggle-visibility {
                    position: absolute;
                    right: 13px;
                    background: none;
                    border: none;
                    padding: 0;
                    cursor: pointer;
                    color: rgba(255, 255, 255, 0.5);
                    display: flex;
                    align-items: center;
                    transition: color 0.2s ease;

                    &:hover {
                        color: rgba(255, 255, 255, 0.9);
                    }

                    i {
                        font-size: var(--font-size-lg);
                    }
                }

                .error-message {
                    color: #ef4444;
                    font-size: var(--font-size-xs);
                    margin-top: 4px;
                    line-height: 1.4;
                }
            }
        `,
    ],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => CustomInputComponent),
            multi: true,
        },
    ],
})
export class CustomInputComponent implements ControlValueAccessor, AfterViewInit {
    @ViewChild('inputEl') inputEl!: ElementRef<HTMLInputElement>;

    @Input() label: string = '';
    @Input() placeholder: string = '';
    @Input() type: string = 'text';
    @Input() id: string = '';
    @Input() name: string = '';
    @Input() autocomplete: string | null = null;
    @Input() autofocus: boolean = false;
    @Input() tooltipText: string = '';
    @Input() icon: string = 'help';
    @Input() required: boolean = false;
    @Input() activeColor: string = '#685fff';
    @Input() errorMessage: string = '';

    @Output() blur = new EventEmitter<void>();

    passwordVisible: boolean = false;

    private readonly supportsTextSecurity: boolean =
        typeof CSS !== 'undefined' &&
        typeof CSS.supports === 'function' &&
        CSS.supports('-webkit-text-security', 'disc');

    private _value: string = '';
    private _disabled: boolean = false;
    private _controlDisabled: boolean = false;

    onChange: (value: string) => void = () => {};
    onTouched: () => void = () => {};

    get value(): string {
        return this._value;
    }

    set value(val: string) {
        this._value = val;
        this.onChange(val);
    }

    @Input()
    get disabled(): boolean {
        return this._disabled;
    }

    set disabled(val: boolean) {
        this._disabled = val;
    }

    get isDisabled(): boolean {
        return this._disabled || this._controlDisabled;
    }

    get isSecret(): boolean {
        return this.type === 'secret';
    }

    get isPassword(): boolean {
        return this.type === 'password';
    }

    get effectiveType(): string {
        if (this.isSecret) {
            if (this.passwordVisible) return 'text';
            return this.supportsTextSecurity ? 'text' : 'password';
        }
        return this.isPassword && this.passwordVisible ? 'text' : this.type;
    }

    get isMasked(): boolean {
        return this.isSecret && !this.passwordVisible && this.supportsTextSecurity;
    }

    get hasToggle(): boolean {
        return this.isSecret || this.isPassword;
    }

    get effectiveAutocomplete(): string | null {
        return this.isSecret ? 'off' : this.autocomplete;
    }

    get isClassIcon(): boolean {
        return !!this.icon && this.icon.trim().includes(' ');
    }

    togglePasswordVisibility(): void {
        this.passwordVisible = !this.passwordVisible;
    }

    writeValue(value: string): void {
        this._value = value || '';
    }

    registerOnChange(fn: (value: string) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this._controlDisabled = isDisabled;
    }

    ngAfterViewInit(): void {
        if (this.autofocus) {
            queueMicrotask(() => this.inputEl?.nativeElement.focus());
        }
    }
}
