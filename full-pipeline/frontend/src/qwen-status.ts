import { Component, OnDestroy, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';

interface QwenStatus {
  status: string; message: string; model: string; httpStatus: number | null; latencyMs: number | null;
  checkedAt: string | null; lastAvailableAt: string | null;
  history: {status: string; message: string; checkedAt: string}[];
}

@Component({selector:'app-qwen-status',standalone:true,imports:[CommonModule,MatButtonModule],
  templateUrl:'./qwen-status.html',styleUrl:'./qwen-status.css'})
export class QwenStatusComponent implements OnInit,OnDestroy {
  readonly status=signal<QwenStatus|null>(null);
  readonly checking=signal(false);
  readonly error=signal('');
  private timer?:ReturnType<typeof setTimeout>;
  private controller?:AbortController;
  private destroyed=false;
  private readonly labels:Record<string,string>={available:'Подключён',unknown:'Нет данных',stale:'Нет свежих данных',
    not_configured:'Не настроен',invalid_config:'Ошибка настроек',unauthorized:'Нет доступа',rate_limited:'Лимит запросов',
    server_error:'Ошибка сервера',endpoint_error:'Ошибка адреса API',model_missing:'Модель не найдена',
    protocol_error:'Неверный ответ',timeout:'Нет ответа',unreachable:'Недоступен',config_mismatch:'Настройки различаются'};
  ngOnInit():void {void this.refresh();}
  ngOnDestroy():void {this.destroyed=true;clearTimeout(this.timer);this.controller?.abort();}
  state():string {return this.error()?'unknown':this.status()?.status||'unknown';}
  label(state:string):string {return this.labels[state]||'Нет данных';}
  async refresh():Promise<void> {
    if(this.checking()||this.destroyed)return;
    clearTimeout(this.timer);this.checking.set(true);
    const controller=new AbortController();this.controller=controller;
    const timeout=setTimeout(()=>controller.abort(),7000);
    try {
      const response=await fetch('/api/qwen/status',{signal:controller.signal,cache:'no-store'});
      if(!response.ok)throw new Error('status unavailable');
      const value=await response.json() as QwenStatus;
      if(!value||typeof value.status!=='string'||!Array.isArray(value.history))throw new Error('invalid status');
      if(!this.destroyed){this.status.set(value);this.error.set('');}
    }catch{
      if(!this.destroyed)this.error.set('Нет связи панели с API. Текущее состояние Qwen неизвестно.');
    }finally{
      clearTimeout(timeout);this.checking.set(false);
      if(!this.destroyed)this.timer=setTimeout(()=>{void this.refresh();},5000);
    }
  }
}
