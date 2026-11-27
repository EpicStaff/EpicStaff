import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormGroup } from '@angular/forms';

import { CsvStrategyModel } from '../../../../../models/strategy.model';
import { CsvFormComponent } from './csv-form.component';

function render(
    params: CsvStrategyModel,
    canUpdate = true
): { fixture: ComponentFixture<CsvFormComponent>; parentForm: FormGroup; host: HTMLElement } {
    const fixture = TestBed.createComponent(CsvFormComponent);
    const parentForm = new FormGroup({});
    fixture.componentRef.setInput('parentForm', parentForm);
    fixture.componentRef.setInput('params', params);
    fixture.componentRef.setInput('canUpdate', canUpdate);
    fixture.detectChanges();
    return { fixture, parentForm, host: fixture.nativeElement as HTMLElement };
}

function setField(parentForm: FormGroup, field: string, value: number | null): void {
    parentForm.get(`strategyParams.additionalParams.${field}`)?.setValue(value);
}

function readOnlyValues(host: HTMLElement): (string | undefined)[] {
    return Array.from(host.querySelectorAll('.config__grid-item--short span')).map((element) =>
        element.textContent?.trim()
    );
}

describe('CsvFormComponent', () => {
    it('falls back to the backend defaults when the document has no stored csv params', () => {
        const { parentForm } = render({});

        expect(parentForm.get('strategyParams.additionalParams')?.value).toEqual({
            rows_in_chunk: 150,
            headers_level: 1,
        });
        expect(parentForm.valid).toBe(true);
    });

    it('keeps stored values, including a headers level of 0', () => {
        const { parentForm } = render({ rows_in_chunk: 40, headers_level: 0 });

        expect(parentForm.get('strategyParams.additionalParams')?.value).toEqual({
            rows_in_chunk: 40,
            headers_level: 0,
        });
        expect(parentForm.valid).toBe(true);
    });

    it('opens a stored legacy rows in chunk of 0 as an invalid form', () => {
        const { parentForm } = render({ rows_in_chunk: 0, headers_level: 1 });

        expect(parentForm.valid).toBe(false);
    });

    it.each([0, -5, 10001, 2.5, null])('is invalid when rows in chunk is %s', (rows) => {
        const { parentForm } = render({});

        setField(parentForm, 'rows_in_chunk', rows);

        expect(parentForm.valid).toBe(false);
    });

    it.each([1, 10000])('accepts rows in chunk at the limit %s', (rows) => {
        const { parentForm } = render({});

        setField(parentForm, 'rows_in_chunk', rows);

        expect(parentForm.valid).toBe(true);
    });

    it.each([-1, 101, 1.5, null])('is invalid when headers level is %s', (level) => {
        const { parentForm } = render({});

        setField(parentForm, 'headers_level', level);

        expect(parentForm.valid).toBe(false);
    });

    it.each([0, 100])('accepts headers level at the limit %s', (level) => {
        const { parentForm } = render({});

        setField(parentForm, 'headers_level', level);

        expect(parentForm.valid).toBe(true);
    });

    it('shows the defaults in read-only mode when nothing is stored', () => {
        const { host } = render({}, false);

        expect(readOnlyValues(host)).toEqual(['150', '1']);
    });

    it('shows a stored headers level of 0 in read-only mode', () => {
        const { host } = render({ rows_in_chunk: 40, headers_level: 0 }, false);

        expect(readOnlyValues(host)).toEqual(['40', '0']);
    });
});
