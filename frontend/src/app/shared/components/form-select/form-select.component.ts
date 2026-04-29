import { CommonModule } from '@angular/common';
import { Component, forwardRef, Input, OnDestroy, OnInit } from '@angular/core';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { Observable, Subscription } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { HelpTooltipComponent } from '../help-tooltip/help-tooltip.component';

@Component({
    selector: 'app-custom-select',
    standalone: true,
    imports: [CommonModule, FormsModule, HelpTooltipComponent],
    template: `
        <div class="form-group">
            <div
                class="label-container"
                *ngIf="label"
            >
                <label [for]="id">{{ label }}</label>
                <app-help-tooltip
                    *ngIf="tooltipText"
                    position="right"
                    [text]="tooltipText"
                ></app-help-tooltip>
            </div>

            <select
                [id]="id"
                [name]="name"
                [(ngModel)]="value"
                (blur)="onTouched()"
                class="text-input"
                [class.error]="errorMessage"
                [disabled]="disabled"
                [style.--active-color]="activeColor"
            >
                <option [ngValue]="null">{{ placeholder }}</option>
                <option
                    *ngFor="let opt of options"
                    [ngValue]="opt[valueProperty]"
                >
                    {{ opt[displayProperty] || opt[valueProperty] }}
                </option>
            </select>

            <div
                class="error-message"
                *ngIf="errorMessage"
            >
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
        `,
    ],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => CustomSelectComponent),
            multi: true,
        },
    ],
})
export class CustomSelectComponent implements ControlValueAccessor, OnInit, OnDestroy {
    @Input() label: string = '';
    @Input() placeholder: string = 'Select...';
    @Input() id: string = '';
    @Input() name: string = '';
    @Input() tooltipText: string = '';
    @Input() activeColor: string = '#685fff';
    @Input() errorMessage: string = '';

    // If caller supplies an observable that returns an ApiGetRequest wrapper, component will subscribe
    @Input() optionsRequest?: Observable<ApiGetRequest<Record<string, unknown>>>;
    // Or the caller can pass options array directly
    @Input() options: Record<string, unknown>[] = [];

    // Which property to display and which to use as value
    @Input() displayProperty: string = 'id';
    @Input() valueProperty: string = 'id';

    private _value: unknown = null;
    private _disabled: boolean = false;
    private subs = new Subscription();

    onChange: (value: unknown) => void = () => {};
    onTouched: () => void = () => {};

    ngOnInit(): void {
        if (this.optionsRequest) {
            const s = this.optionsRequest.subscribe((res) => {
                if (res && (res as ApiGetRequest<Record<string, unknown>>).results) {
                    this.options = (res as ApiGetRequest<Record<string, unknown>>).results;
                } else if (Array.isArray(res)) {
                    this.options = res as Record<string, unknown>[];
                }
            });
            this.subs.add(s);
        }
    }

    ngOnDestroy(): void {
        this.subs.unsubscribe();
    }

    get value(): unknown {
        return this._value;
    }

    set value(val: unknown) {
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

    writeValue(value: unknown): void {
        this._value = value ?? null;
    }

    registerOnChange(fn: (value: unknown) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this._disabled = isDisabled;
    }
}
