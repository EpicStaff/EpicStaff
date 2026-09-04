import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

import { Language } from '../../../../../../../shared/constants/languages-selector.constants';
import { ClickOutsideDirective } from '../../../../../../../shared/directives/click-outside.directive';

@Component({
    selector: 'app-language-selector',
    standalone: true,
    imports: [CommonModule, FormsModule, ReactiveFormsModule, ClickOutsideDirective],
    templateUrl: './language-selector.component.html',
    styleUrls: ['./language-selector.component.scss'],
})
export class LanguageSelectorComponent {
    @Input() selectedLanguage: string | null = 'auto';
    @Input() languages: Language[] = [];
    @Input() label: string = 'Language';
    @Input() disabled: boolean = false;

    @Output() languageChange = new EventEmitter<string | null>();

    isOpen = false;

    toggleDropdown(): void {
        if (!this.disabled) {
            this.isOpen = !this.isOpen;
        }
    }

    selectLanguage(langId: string | null): void {
        this.selectedLanguage = langId;
        this.languageChange.emit(langId);
        this.isOpen = false;
    }

    getSelectedLanguageName(): string {
        const selected = this.languages.find((lang) => lang.id === this.selectedLanguage);
        return selected ? selected.name : 'Select a language';
    }
}
