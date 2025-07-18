import { Component, Input, OnInit } from '@angular/core';
import {
  FormArray,
  FormGroup,
  FormBuilder,
  ControlContainer,
  ReactiveFormsModule,
  FormGroupDirective,
} from '@angular/forms';
import { CommonModule } from '@angular/common';
import { HelpTooltipComponent } from '../../../shared/components/help-tooltip/help-tooltip.component';

@Component({
  selector: 'app-input-map',
  standalone: true,
  imports: [ReactiveFormsModule, CommonModule],
  viewProviders: [
    {
      provide: ControlContainer,
      useExisting: FormGroupDirective,
    },
  ],
  template: `
    <div class="input-map-container" formArrayName="input_map">
      <div class="input-map-list">
        @for (pair of pairs.controls; let i = $index; track pair) {
        <div class="input-map-item" [formGroupName]="i">
          <div class="input-map-fields">
            <div class="input-wrapper">
              <input
                type="text"
                formControlName="key"
                placeholder="Function Argument Name"
                [style.--active-color]="activeColor"
                autocomplete="off"
              />
            </div>
            <div class="equals-sign">=</div>
            <div class="input-wrapper">
              <input
                type="text"
                formControlName="value"
                placeholder="Domain Variable Name"
                [style.--active-color]="activeColor"
                autocomplete="off"
              />
            </div>
            <i class="ti ti-trash delete-icon" (click)="removePair(i)"></i>
          </div>
        </div>
        }
      </div>
      <button type="button" class="add-pair-btn" (click)="addPair()">
        <i class="ti ti-plus"></i> Add Input
      </button>
    </div>
  `,
  styles: [
    `
      .input-map-container {
        display: flex;
        flex-direction: column;
        gap: 12px;
        width: 100%;
      }

      .input-map-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.8rem;
        color: rgba(255, 255, 255, 0.7);
        margin-bottom: 4px;
        padding: 0 4px;
      }

      .function-arg {
        flex: 1;
      }

      .domain-var {
        flex: 1;
      }

      .equals {
        width: 20px;
        text-align: center;
      }

      .input-map-list {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        width: 100%;
        min-width: 0;
      }

      .input-map-item {
        width: 100%;
      }

      .input-map-fields {
        display: flex;
        gap: 0.5rem;
        align-items: center;
        width: 100%;
      }

      .input-wrapper {
        flex: 1;
        min-width: 0;
      }

      .equals-sign {
        color: #fff;
        font-weight: 500;
        margin: 0 -2px;
      }

      .input-wrapper input {
        width: 100%;
        padding: 0.5rem 0.75rem;
        background-color: var(--color-nodes-input-bg);
        border: 1px solid var(--color-divider-subtle);
        border-radius: 6px;
        color: #fff;
        font-size: 0.875rem;
        outline: none;
        transition: border-color 0.2s ease;

        &:focus {
          border-color: var(--active-color);
        }

        &::placeholder {
          color: rgba(255, 255, 255, 0.3);
        }
      }

      .delete-icon {
        font-size: 1rem;
        cursor: pointer;
        color: #ccc;
        padding: 0.2rem;
        border-radius: 4px;
        transition: all 0.2s ease;
        flex-shrink: 0;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;

        &:hover {
          color: red;
          background-color: rgba(255, 0, 0, 0.1);
        }
      }

      .add-pair-btn {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        background: var(--color-action-btn-background);
        border: 1px solid var(--color-divider-subtle);
        border-radius: 4px;
        color: var(--color-text-primary);
        transition: background-color 0.2s;
        cursor: pointer;
        font-size: 0.875rem;

        &:hover {
          background: var(--color-action-btn-background-hover);
        }

        i {
          font-size: 16px;
        }
      }
    `,
  ],
})
export class InputMapComponent implements OnInit {
  @Input() activeColor: string = '#685fff';

  constructor(
    private controlContainer: ControlContainer,
    private fb: FormBuilder
  ) {}

  ngOnInit() {
    // Ensure there's always at least one empty input map initially
    if (this.pairs.length === 0) {
      this.addPair();

      // Mark the initial empty input as pristine and untouched
      // This prevents it from being considered as a "change" for the unsaved changes guard
      setTimeout(() => {
        this.pairs.at(0).markAsPristine();
        this.pairs.at(0).markAsUntouched();
        this.pairs.updateValueAndValidity();
      });
    }
  }

  get parentForm(): FormGroup {
    return this.controlContainer.control as FormGroup;
  }

  get pairs(): FormArray {
    return this.parentForm.get('input_map') as FormArray;
  }

  addPair() {
    this.pairs.push(
      this.fb.group({
        key: [''],
        value: [''],
      })
    );
  }

  removePair(index: number) {
    this.pairs.removeAt(index);
    if (this.pairs.length === 0) {
      this.addPair();
    }
  }
}
