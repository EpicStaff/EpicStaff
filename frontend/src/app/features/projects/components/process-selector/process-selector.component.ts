import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';

@Component({
  selector: 'app-process-selector',
  templateUrl: './process-selector.component.html',
  styleUrls: ['./process-selector.component.scss'],
  standalone: true,
  imports: [CommonModule, FormsModule, AppIconComponent, HelpTooltipComponent],
})
export class ProcessSelectorComponent implements OnInit {
  @Input() initialValue: 'sequential' | 'hierarchical' = 'sequential';
  @Output() valueChange = new EventEmitter<'sequential' | 'hierarchical'>();

  public selectedValue: 'sequential' | 'hierarchical' = 'sequential';

  constructor() {}

  ngOnInit(): void {
    this.selectedValue = this.initialValue || 'sequential';
  }

  public onProcessTypeSelect(value: 'sequential' | 'hierarchical'): void {
    this.selectedValue = value;
    this.valueChange.emit(value);
  }
}
