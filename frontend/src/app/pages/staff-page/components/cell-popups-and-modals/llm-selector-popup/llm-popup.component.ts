import {
  Component,
  OnInit,
  OnChanges,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  SimpleChanges,
  ViewChild,
  ElementRef,
  OnDestroy,
  AfterViewInit,
  HostListener,
} from '@angular/core';
import { NgClass, NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, forkJoin } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { FullLLMConfigService } from '../../../../../features/settings-dialog/services/llms/full-llm-config.service';
import { FullRealtimeConfigService } from '../../../../../features/settings-dialog/services/realtime-llms/full-reamtime-config.service';
import { LlmItemComponent } from './llm-item/llm-item.component';
import { MergedConfig } from '../../../../../services/full-agent.service';

@Component({
  selector: 'app-llm-popup',
  standalone: true,
  imports: [NgFor, FormsModule, NgIf, NgClass, LlmItemComponent],
  templateUrl: './llm-popup.component.html',
  styleUrls: ['./llm-popup.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LLMPopupComponent
  implements OnInit, OnChanges, OnDestroy, AfterViewInit
{
  // Input/Output
  @Input() public cellValue: MergedConfig[] = [];
  @Output() public configsSelected = new EventEmitter<MergedConfig[]>();
  @Output() public cancel = new EventEmitter<void>();

  @ViewChild('searchInput') private searchInput!: ElementRef;

  public searchTerm: string = '';
  public activeTab: 'llm' | 'realtime' = 'llm';
  public loading: boolean = true;

  // LLM Models
  public llmConfigs: any[] = [];
  public selectedLLMId: number | null = null;
  public selectedLLM: any = null;

  // Realtime Models
  public realtimeConfigs: any[] = [];
  public selectedRealtimeId: number | null = null;
  public selectedRealtime: any = null;

  // Cached filtered arrays
  private _filteredLLMs: MergedConfig[] = [];
  private _filteredRealtimeModels: MergedConfig[] = [];
  private _lastSearchTerm: string = '';

  private readonly destroyed$ = new Subject<void>();

  constructor(
    private readonly fullLLMConfigService: FullLLMConfigService,
    private readonly fullRealtimeConfigService: FullRealtimeConfigService,
    private readonly cdr: ChangeDetectorRef
  ) {}

  public ngOnInit(): void {
    console.log('cellValue', this.cellValue);
    this.loadConfigs();
  }

  public ngOnChanges(changes: SimpleChanges): void {
    if (changes['cellValue']) {
      this.preSelectConfigs();
    }
  }
  public ngAfterViewInit(): void {
    if (this.searchInput) {
      this.searchInput.nativeElement.focus();
    }
    // Force a change detection cycle after view init
    setTimeout(() => {
      this.cdr.detectChanges();
    }, 0);
  }
  public ngOnDestroy(): void {
    this.destroyed$.next();
    this.destroyed$.complete();
  }

  // Load all configurations from services
  private loadConfigs(): void {
    this.loading = true;
    this.cdr.markForCheck();

    // Use forkJoin to load both config types in parallel
    forkJoin({
      llmConfigs: this.fullLLMConfigService.getFullLLMConfigs(),
      realtimeConfigs: this.fullRealtimeConfigService.getFullRealtimeConfigs(),
    })
      .pipe(takeUntil(this.destroyed$))
      .subscribe({
        next: ({ llmConfigs, realtimeConfigs }) => {
          // Process LLM configs
          this.llmConfigs = llmConfigs;

          // Process Realtime configs
          this.realtimeConfigs = realtimeConfigs.fullConfigs;

          // Clear cached filtered arrays
          this._filteredLLMs = [];
          this._filteredRealtimeModels = [];

          // Preselect configs and update UI
          this.preSelectConfigs();
          this.loading = false;
          this.cdr.markForCheck();
        },
        error: (err) => {
          console.error('Error fetching configurations:', err);
          this.loading = false;
          this.cdr.markForCheck();
        },
      });
  }

  private preSelectConfigs(): void {
    if (!this.cellValue || !this.cellValue.length) return;

    try {
      // Find LLM config in cell value
      const llmConfig: MergedConfig | undefined = this.cellValue.find(
        (config) => config.type === 'llm'
      );
      if (llmConfig) {
        const matchedConfig = this.llmConfigs.find(
          (c) => c.id === llmConfig.id
        );
        if (matchedConfig) {
          this.selectedLLMId = matchedConfig.id;
          this.selectedLLM = matchedConfig;
        }
      }

      // Find realtime config in cell value
      const realtimeConfig = this.cellValue.find(
        (config) => config.type === 'realtime'
      );
      if (realtimeConfig) {
        const matchedConfig = this.realtimeConfigs.find(
          (c) => c.id === realtimeConfig.id
        );
        if (matchedConfig) {
          this.selectedRealtimeId = matchedConfig.id;
          this.selectedRealtime = matchedConfig;
        }
      }

      this.cdr.markForCheck();
    } catch (err) {
      console.error('Error pre-selecting configs:', err);
    }
  }

  public getModelName(config: any): string {
    if (!config) return 'Unknown Model';

    // For FullLLMConfig objects
    if (config.modelDetails?.name) {
      return config.modelDetails.name;
    }

    // For MergedConfig objects
    if (config.model_name) {
      return config.model_name;
    }

    // For legacy config objects
    if (config.configuration?.model_name) {
      return config.configuration.model_name;
    }

    return 'Unnamed Model';
  }

  public setActiveTab(tab: 'llm' | 'realtime'): void {
    this.activeTab = tab;
    this.cdr.markForCheck();
  }

  public get filteredLLMs(): MergedConfig[] {
    // Only recalculate if search term changed or configs changed
    if (
      this._lastSearchTerm !== this.searchTerm ||
      this._filteredLLMs.length === 0
    ) {
      this._lastSearchTerm = this.searchTerm;

      if (!this.llmConfigs || this.llmConfigs.length === 0) {
        this._filteredLLMs = [];
        return this._filteredLLMs;
      }

      const configs = this.llmConfigs.map((config) => {
        return {
          id: config.id,
          custom_name: config.custom_name,
          model_name: config.modelDetails?.name || 'Unknown Model',
          type: 'llm' as const,
          provider_id: config.modelDetails?.llm_provider,
          provider_name: config.providerDetails?.name || 'Unknown Provider',
        };
      });

      if (!this.searchTerm) {
        this._filteredLLMs = configs;
      } else {
        const search = this.searchTerm.toLowerCase();
        this._filteredLLMs = configs.filter((config) => {
          const modelName = config.model_name.toLowerCase();
          const customName = (config.custom_name || '').toLowerCase();
          return modelName.includes(search) || customName.includes(search);
        });
      }
    }

    return this._filteredLLMs;
  }

  public get filteredRealtimeModels(): MergedConfig[] {
    // Only recalculate if search term changed or configs changed
    if (
      this._lastSearchTerm !== this.searchTerm ||
      this._filteredRealtimeModels.length === 0
    ) {
      if (!this.realtimeConfigs || this.realtimeConfigs.length === 0) {
        this._filteredRealtimeModels = [];
        return this._filteredRealtimeModels;
      }

      const configs = this.realtimeConfigs.map((config) => {
        return {
          id: config.id,
          custom_name: config.custom_name,
          model_name: config.modelDetails?.name || 'Unknown Model',
          type: 'realtime' as const,
          provider_id: config.modelDetails?.provider,
          provider_name: config.providerDetails?.name || 'Unknown Provider',
        };
      });

      if (!this.searchTerm) {
        this._filteredRealtimeModels = configs;
      } else {
        const search = this.searchTerm.toLowerCase();
        this._filteredRealtimeModels = configs.filter((config) => {
          const modelName = config.model_name.toLowerCase();
          const customName = (config.custom_name || '').toLowerCase();
          return modelName.includes(search) || customName.includes(search);
        });
      }
    }

    return this._filteredRealtimeModels;
  }

  public onSelectLLM(item: MergedConfig): void {
    console.log('onSelectLLM called with item:', item);
    console.log('Current selectedLLMId:', this.selectedLLMId);

    if (this.selectedLLMId === item.id) {
      // If already selected, unselect it
      console.log('Unselecting LLM item');
      this.selectedLLMId = null;
      this.selectedLLM = null;
    } else {
      // Select this item
      console.log('Selecting LLM item');
      this.selectedLLMId = item.id;
      // Find the original config object
      this.selectedLLM = this.llmConfigs.find(
        (config) => config.id === item.id
      );
    }

    console.log('New selectedLLMId:', this.selectedLLMId);
    this.cdr.detectChanges();
  }

  public onSelectRealtime(item: MergedConfig): void {
    console.log('onSelectRealtime called with item:', item);
    console.log('Current selectedRealtimeId:', this.selectedRealtimeId);

    if (this.selectedRealtimeId === item.id) {
      // If already selected, unselect it
      console.log('Unselecting Realtime item');
      this.selectedRealtimeId = null;
      this.selectedRealtime = null;
    } else {
      // Select this item
      console.log('Selecting Realtime item');
      this.selectedRealtimeId = item.id;
      // Find the original config object
      this.selectedRealtime = this.realtimeConfigs.find(
        (config) => config.id === item.id
      );
    }

    console.log('New selectedRealtimeId:', this.selectedRealtimeId);
    this.cdr.detectChanges();
  }

  public onSave(): void {
    const selectedConfigs: MergedConfig[] = [];

    // Add selected LLM if any
    if (this.selectedLLM) {
      selectedConfigs.push({
        id: this.selectedLLM.id,
        custom_name: this.selectedLLM.custom_name,
        model_name: this.selectedLLM.modelDetails?.name || 'Unknown Model',
        type: 'llm',
        provider_id: this.selectedLLM.modelDetails?.llm_provider,
        provider_name:
          this.selectedLLM.providerDetails?.name || 'Unknown Provider',
      });
    }

    // Add selected Realtime if any
    if (this.selectedRealtime) {
      selectedConfigs.push({
        id: this.selectedRealtime.id,
        custom_name: this.selectedRealtime.custom_name,
        model_name: this.selectedRealtime.modelDetails?.name || 'Unknown Model',
        type: 'realtime',
        provider_id: this.selectedRealtime.modelDetails?.provider,
        provider_name:
          this.selectedRealtime.providerDetails?.name || 'Unknown Provider',
      });
    }

    this.configsSelected.emit(selectedConfigs);
  }

  public onCancel(): void {
    this.cancel.emit();
  }
}
