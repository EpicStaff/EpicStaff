import {
    Component,
    Input,
    Output,
    EventEmitter,
    forwardRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
    ControlValueAccessor,
    FormsModule,
    NG_VALUE_ACCESSOR,
} from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatIconModule } from '@angular/material/icon';

@Component({
    selector: 'app-custom-input',
    standalone: true,
    imports: [CommonModule, FormsModule, MatTooltipModule, MatIconModule],
    template: `
        <div class="form-group">
            <div class="label-container" *ngIf="label">
                <label [for]="id">{{ label }}</label>
                <ng-container *ngIf="tooltipText">
                    <mat-icon
                        *ngIf="!isClassIcon"
                        [matTooltip]="tooltipText"
                        matTooltipPosition="right"
                        matTooltipClass="custom-tooltip"
                        class="help-icon"
                    >
                        {{ icon || 'help' }}
                    </mat-icon>
                    <i
                        *ngIf="isClassIcon"
                        [class]="icon"
                        [matTooltip]="tooltipText"
                        matTooltipPosition="right"
                        matTooltipClass="custom-tooltip"
                        class="help-icon class-icon"
                    ></i>
                </ng-container>
            </div>
            <input
                [type]="type"
                [id]="id"
                [name]="name"
                [placeholder]="placeholder"
                [(ngModel)]="value"
                (blur)="onTouched()"
                class="text-input"
                [class.error]="errorMessage"
                [disabled]="disabled"
                [autofocus]="autofocus"
                [style.--active-color]="activeColor"
            />
            <div class="error-message" *ngIf="errorMessage">
                {{ errorMessage }}
            </div>
        </div>
    `,
    styles: [
        `
            .form-group {
                .label-container {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    margin-bottom: 8px;
                }

                label {
                    display: block;
                    font-size: 14px;
                    color: rgba(255, 255, 255, 0.7);
                    margin: 0;
                }

                .help-icon {
                    font-size: 18px;
                    width: 18px;
                    height: 18px;
                    color: rgba(255, 255, 255, 0.6);
                    cursor: help;
                    transition: color 0.2s ease;

                    &:hover {
                        color: rgba(255, 255, 255, 0.9);
                    }

                    &.class-icon {
                        display: inline-flex;
                        align-items: center;
                        justify-content: center;
                    }
                }

                .text-input {
                    width: 100%;
                    padding: 8px 12px;
                    background-color: var(--color-input-background);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 6px;
                    color: white;
                    font-size: 14px;
                    transition: border-color 0.2s ease;

                    &:focus {
                        outline: none;
                        border-color: var(--active-color, #685fff);
                    }

                    &.error {
                        border-color: #ef4444;
                    }
                }

                .error-message {
                    color: #ef4444;
                    font-size: 12px;
                    margin-top: 4px;
                    line-height: 1.4;
                }
            }

            :host ::ng-deep .custom-tooltip {
                background: #232323 !important;
                color: #fff !important;
                font-size: 0.9rem !important;
                max-width: 300px !important;
                border: 1px solid rgba(255, 255, 255, 0.1) !important;
                box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3) !important;
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
export class CustomInputComponent implements ControlValueAccessor {
    @Input() label: string = '';
    @Input() placeholder: string = '';
    @Input() type: string = 'text';
    @Input() id: string = '';
    @Input() name: string = '';
    @Input() autofocus: boolean = false;
    @Input() tooltipText: string = '';
    @Input() icon: string = 'help';
    @Input() activeColor: string = '#685fff';
    @Input() errorMessage: string = '';

    private _value: string = '';
    private _disabled: boolean = false;

    onChange: any = () => {};
    onTouched: any = () => {};

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

    get isClassIcon(): boolean {
        return !!this.icon && this.icon.trim().includes(' ');
    }

    writeValue(value: string): void {
        this._value = value || '';
    }

    registerOnChange(fn: any): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: any): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this._disabled = isDisabled;
    }
}
