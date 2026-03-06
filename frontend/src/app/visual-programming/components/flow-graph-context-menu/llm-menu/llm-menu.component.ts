import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { LLM_Config_Service } from '../../../../features/settings-dialog/services/llms/llm-config.service';
import { GetLlmConfigRequest } from '../../../../features/settings-dialog/models/llms/LLM_config.model';
import { NodeType } from '../../../core/enums/node-type';

@Component({
  selector: 'app-llm-menu',
  standalone: true,
  imports: [CommonModule],
  template: `
    <ul>
      <li
        *ngFor="let config of filteredConfigs; trackBy: trackById"
        (click)="onConfigClicked(config)"
      >
        <i class="ti ti-brain"></i>
        <span class="config-name">{{ config.custom_name }}</span>
        <i class="ti ti-plus plus-icon"></i>
      </li>
    </ul>
  `,
  styles: [
    `
      ul {
        list-style: none;
        padding: 0 16px;
        margin: 0;
      }
      li {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 16px;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.2s ease;
        position: relative;
        gap: 16px;
        overflow: hidden;
      }
      li:hover {
        background: #2a2a2a;
        color: #fff;
      }
      li i {
        font-size: 18px;
        color: #e0575b;
      }

      .config-name {
        flex: 1;
        overflow: hidden;
        white-space: nowrap;
        text-overflow: ellipsis;
      }
      .plus-icon {
        font-size: 18px;
        color: #bbb;
        opacity: 0;
        transition: opacity 0.2s ease, color 0.2s ease;
      }
      li:hover .plus-icon {
        opacity: 1;
        color: #fff;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmMenuComponent implements OnInit {
  @Input() public searchTerm: string = '';
  @Output() public nodeSelected = new EventEmitter<{
    type: NodeType.LLM;
    data: GetLlmConfigRequest;
  }>();

  public configs: GetLlmConfigRequest[] = [];

  constructor(
    private llmConfigService: LLM_Config_Service,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.llmConfigService.getAllConfigsLLM().subscribe({
      next: (configs: GetLlmConfigRequest[]) => {
        this.configs = configs;
        this.cdr.markForCheck();
      },
      error: (err) => {
        console.error('Error fetching LLM configs:', err);
      },
    });
  }

  public get filteredConfigs(): GetLlmConfigRequest[] {
    return this.configs.filter((config) =>
      config.custom_name.toLowerCase().includes(this.searchTerm.toLowerCase())
    );
  }

  public onConfigClicked(config: GetLlmConfigRequest): void {
    console.log('Config clicked');

    this.nodeSelected.emit({ type: NodeType.LLM, data: config });
  }

  public trackById(index: number, config: GetLlmConfigRequest): number {
    return config.id;
  }
}
