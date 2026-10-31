import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ActivityFeed } from './activity-feed';
import { GeneratedPanel } from './generated/generated-panel';
import { configureProductApi, productFetch } from './product-api';

@Component({selector:'app-root',standalone:true,imports:[CommonModule,FormsModule,MatButtonModule,MatCardModule,MatFormFieldModule,MatSelectModule,MatProgressBarModule,GeneratedPanel,ActivityFeed],templateUrl:'./app.html'})
export class AppComponent implements OnInit {
  spec:any; role=''; roles:string[]=[]; token=sessionStorage.getItem('demo-token')||'';
  loggedRole=sessionStorage.getItem('demo-role')||''; error=''; loading=true;
  constructor(private cd:ChangeDetectorRef){}
  get requiresLogin(){return this.spec?.requiresLogin!==false;}
  get publicRole(){return (this.spec?.capabilities||[]).some((x:string)=>x.toLowerCase().includes('parking'))?'driver':(this.spec?.roles||[]).find((r:string)=>r==='user')||(this.spec?.roles||[]).find((r:string)=>r!=='admin')||'user';}
  get purpose(){return this.spec?.businessGoal||this.spec?.summary||'';}
  async ngOnInit(){await this.perform(()=>this.initialize());}
  async initialize(){
    this.spec=await this.api('/api/schema'); document.title=this.spec.title||'Приложение';
    this.roles=[...new Set<string>(this.spec.roles||[])];
    this.role=this.roles.includes(this.loggedRole)?this.loggedRole:this.roles[0]||this.publicRole;
    configureProductApi(this.publicRole,!this.requiresLogin);
    if(!this.requiresLogin)await this.authenticate(this.publicRole);
  }
  async api(path:string,method='GET',body?:any){
    const res=await productFetch(path,{method,headers:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});
    if(!res.ok){
      let detail='';try{const data=await res.json();detail=data.error||data.message||'';}catch{}
      if(res.status===401)this.clearSession();
      throw new Error(detail||'Не удалось подключиться. Повторите попытку.');
    }
    return res.status===204?null:res.json();
  }
  async perform(task:()=>Promise<void>){
    this.loading=true;this.error='';
    try{await task();}catch(error:any){this.error=error instanceof TypeError?'Нет связи с сервером. Проверьте соединение.':error.message||'Не удалось выполнить действие.';}
    finally{this.loading=false;this.cd.markForCheck();}
  }
  async retry(){await this.perform(()=>this.initialize());}
  async authenticate(role:string){
    const data=await this.api('/api/auth/login','POST',{role}); this.token=data.token;this.loggedRole=data.role;
    sessionStorage.setItem('demo-token',this.token);sessionStorage.setItem('demo-role',this.loggedRole);
  }
  async login(){await this.perform(()=>this.authenticate(this.role));}
  clearSession(){this.token='';this.loggedRole='';sessionStorage.removeItem('demo-token');sessionStorage.removeItem('demo-role');}
  logout(){this.clearSession();this.error='';}
}
