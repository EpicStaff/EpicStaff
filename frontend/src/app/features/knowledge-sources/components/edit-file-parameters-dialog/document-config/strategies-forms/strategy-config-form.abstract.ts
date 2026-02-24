import { AbstractControl, FormBuilder, FormGroup } from "@angular/forms";
import { Component, inject, input, OnChanges, OnDestroy, SimpleChanges } from "@angular/core";
import { StrategyModel } from "../../../../models/strategy.model";

@Component({
    template: '',
})
export abstract class StrategyForm<T extends StrategyModel> implements OnChanges, OnDestroy {
    protected fb = inject(FormBuilder);
    protected strategyForm!: FormGroup;

    parentForm = input.required<FormGroup>();
    params = input.required<T>();

    // Rebuild form on each document change
    ngOnChanges(changes: SimpleChanges): void {
        this.parentForm().removeControl('strategyParams');
        this.strategyForm = this.initializeForm(this.params());
        this.parentForm().addControl('strategyParams', this.strategyForm);
    }

    ngOnDestroy() {
        this.parentForm().removeControl('strategyParams');
    }

    getMainParamControl(control: string): AbstractControl | null | undefined {
        return this.strategyForm.get('mainParams')?.get(control)
    }

    protected abstract initializeForm(config: T): FormGroup;
}
