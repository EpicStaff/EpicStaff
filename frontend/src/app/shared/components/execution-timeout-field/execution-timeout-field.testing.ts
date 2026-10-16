import { TestBed } from '@angular/core/testing';

import { ExecutionTimeoutFieldComponent } from './execution-timeout-field.component';
import { ExecutionTimeoutFormField } from './execution-timeout-form-field';

/**
 * Types `text` as the user does, without leaving the input (no blur, no Enter), into a separate
 * `ExecutionTimeoutFieldComponent` this mounts bound to the form's `field` object. For a form spec whose template
 * does not render the field: the form sees the edit through the shared field, as it does from its own input.
 */
export function typeIntoExecutionTimeout(field: ExecutionTimeoutFormField, text: string): void {
    const fixture = TestBed.createComponent(ExecutionTimeoutFieldComponent);
    fixture.componentRef.setInput('field', field);
    fixture.detectChanges();
    const input = (fixture.nativeElement as HTMLElement).querySelector('input')!;
    input.value = text;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}
