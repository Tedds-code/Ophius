"""Native Tk application. Widgets remain alive while observations refresh."""
from __future__ import annotations

import json
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import unicodedata

from .transport import normalize_packet, strict_json

MODES = {'Within limits':'normal', 'Caution values':'caution', 'Critical values':'critical',
         'Heart-rate collapse':'cardiac_arrest', 'Prolonged QTc':'qtc', 'High cabin CO₂':'co2'}


def searchable(value):
    return ' '.join(unicodedata.normalize('NFKD', str(value)).lower().replace('_',' ').split())


def matches(text, query):
    haystack = searchable(text)
    return all(word in haystack for word in searchable(query).split())


def visible_live_rows(snapshot, specifications):
    categories = {r['key']:r.get('category') for r in specifications}
    return [row for row in snapshot['readings']
            if categories.get(row['key']) in {'cardiovascular','respiratory','vital','environment'}
            and (row['key'] != 'cabin_co2' or row.get('value') is not None)]


def value_text(value):
    return '—' if value is None else f'{value:g}' if isinstance(value, (int,float)) else str(value)


class NativeApp:
    def __init__(self, root, monitor, simulator, notifications, stop, window_signals, hidden=False):
        self.root, self.monitor, self.simulator = root, monitor, simulator
        self.notifications, self.stop, self.window_signals = notifications, stop, window_signals
        self.meta = monitor.kb.meta()
        self.aid = None
        self.snapshot = None
        self.last_findings = None
        self.symptom_vars, self.context_vars, self.manual_vars = {}, {}, {}
        self.finding_items, self.library_items, self.alert_items = [], [], []
        self.med_check = None
        self.crew_var = tk.StringVar()
        self.mode_var = tk.StringVar(value='Within limits')
        self.search_var, self.library_search = tk.StringVar(), tk.StringVar()
        self.exposures_var, self.allergies_var = tk.StringVar(), tk.StringVar()
        self.med_var, self.med_note = tk.StringVar(), tk.StringVar()
        self.forecast_key = tk.StringVar(value='nuclear_source_dose')
        self.forecast_rate, self.forecast_days = tk.StringVar(value='0.1'), tk.StringVar(value='21')
        root.title('Ophius 2.0 — native desktop')
        root.geometry(f'{min(1180, root.winfo_screenwidth()-60)}x{min(820, root.winfo_screenheight()-80)}'); root.minsize(850, 600)
        root.protocol('WM_DELETE_WINDOW', self.hide)
        style = ttk.Style(root)
        if 'clam' in style.theme_names(): style.theme_use('clam')
        style.configure('Treeview', rowheight=28)
        style.configure('Title.TLabel', font=('TkDefaultFont', 18, 'bold'))
        style.configure('Warning.TLabel', foreground='#a92d24')
        self._build()
        self.search_var.trace_add('write', lambda *_: self.filter_symptoms())
        self.library_search.trace_add('write', lambda *_: self.filter_library())
        self.med_var.trace_add('write', lambda *_: self.reset_medication())
        self.crew_select.bind('<<ComboboxSelected>>', lambda _: self.select_crew(self.crew_var.get()))
        self.load_crew()
        self.refresh()
        if hidden: root.withdraw()
        else: root.deiconify()
        self.after_id = root.after(500, self.poll)

    def call(self, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            messagebox.showerror('Ophius', str(exc), parent=self.root)
            return None

    def _build(self):
        outer = ttk.Frame(self.root, padding=14); outer.pack(fill='both', expand=True)
        top = ttk.Frame(outer); top.pack(fill='x')
        ttk.Label(top, text='Ophius', style='Title.TLabel').pack(side='left', padx=(0,22))
        ttk.Label(top, text='Astronaut').pack(side='left', padx=5)
        self.crew_select = ttk.Combobox(top, textvariable=self.crew_var, state='readonly', width=18)
        self.crew_select.pack(side='left')
        ttk.Button(top, text='Import profile', command=lambda:self.import_json('profile')).pack(side='left', padx=8)
        ttk.Button(top, text='Quit & save', command=self.quit).pack(side='right')
        ttk.Button(top, text='Minimize & monitor', command=self.root.iconify).pack(side='right', padx=8)
        self.status = ttk.Label(outer, text='Starting monitor…'); self.status.pack(fill='x', pady=(12,3))
        banner = ttk.Frame(outer); banner.pack(fill='x', pady=(0,8))
        self.warning = ttk.Label(banner, style='Warning.TLabel'); self.warning.pack(side='left')
        ttk.Button(banner, text='Review pending warnings', command=self.show_alerts).pack(side='right')
        controls = ttk.LabelFrame(outer, text='Simulation', padding=8); controls.pack(fill='x', pady=(0,10))
        self.mode_combo = ttk.Combobox(controls, textvariable=self.mode_var, values=list(MODES), state='readonly', width=26)
        self.mode_combo.pack(side='left')
        for label, action in [('Start continuous','start'),('One reading / scenario','once'),('Stop','stop')]:
            ttk.Button(controls, text=label, command=lambda a=action:self.simulate(a)).pack(side='left', padx=5)
        self.sim_status = ttk.Label(controls, text='Stopped'); self.sim_status.pack(side='right')
        self.tabs = ttk.Notebook(outer); self.tabs.pack(fill='both', expand=True)
        self.frames = {}
        for key, title in [('overview','Vitals'),('results','Labs & dose'),('findings','Findings'),
                           ('symptoms','Symptoms'),('library','Treatments'),('medication','Medication safety'),
                           ('history','History'),('forecasts','Forecasts'),('profile','Profile')]:
            frame=ttk.Frame(self.tabs,padding=10); self.frames[key]=frame; self.tabs.add(frame,text=title)
        self.live_tree=self.tree(self.frames['overview'], ['Measurement','Current','Personal baseline','Status','Source / acquired','Context'])
        self.live_tree.pack(fill='both',expand=True)
        ttk.Label(self.frames['overview'], text='CO₂ is shown only while a reading is available. Baselines remain separate from current measurements.').pack(anchor='w',pady=8)
        buttons=ttk.Frame(self.frames['results']); buttons.pack(fill='x',pady=(0,8))
        ttk.Button(buttons,text='Import blood-test JSON',command=lambda:self.import_json('lab')).pack(side='left')
        ttk.Button(buttons,text='Import sensor / dose JSON',command=lambda:self.import_json('packet')).pack(side='left',padx=8)
        self.results_tree=self.tree(self.frames['results'],['Measurement','Current','Personal baseline','Status','Source / acquired','Context']);self.results_tree.pack(fill='both',expand=True)
        self.finding_list,self.finding_text=self.split_details(self.frames['findings'])
        self.finding_list.bind('<<ListboxSelect>>',lambda _:self.show_finding())
        self._build_symptoms()
        ttk.Label(self.frames['library'],text='Search conditions, medications and treatment details').pack(anchor='w')
        self.library_entry=ttk.Entry(self.frames['library'],textvariable=self.library_search);self.library_entry.pack(fill='x',pady=8)
        self.library_count=ttk.Label(self.frames['library']);self.library_count.pack(anchor='w')
        self.library_list,self.library_text=self.split_details(self.frames['library'])
        self.library_list.bind('<<ListboxSelect>>',lambda _:self.show_library())
        self._build_medication()
        bar=ttk.Frame(self.frames['history']);bar.pack(fill='x')
        ttk.Button(bar,text='Refresh history',command=self.refresh_history).pack(side='left')
        ttk.Button(bar,text='Export history JSON',command=self.export_history).pack(side='left',padx=8)
        self.history_text=self.text(self.frames['history']);self.history_text.pack(fill='both',expand=True,pady=8)
        self._build_forecasts()
        pbar=ttk.Frame(self.frames['profile']);pbar.pack(fill='x')
        ttk.Button(pbar,text='Export profile JSON',command=self.export_profile).pack(side='left')
        self.profile_text=self.text(self.frames['profile']);self.profile_text.pack(fill='both',expand=True,pady=8)
        ttk.Label(outer,text='Local native application · Normal raw readings expire after 60 seconds · Research prototype').pack(anchor='w',pady=(8,0))
        self.tabs.bind('<<NotebookTabChanged>>',self.tab_changed)

    def tree(self,parent,columns):
        tree=ttk.Treeview(parent,columns=columns,show='headings',selectmode='browse')
        widths=[180,105,140,100,190,270]
        for i,c in enumerate(columns):tree.heading(c,text=c);tree.column(c,width=widths[i],minwidth=65,stretch=True)
        for status,color in [('critical','#b62323'),('caution','#a15c00'),('invalid','#8b3e78'),('needs_context','#775a00'),('missing','#777777'),('stale','#777777')]:tree.tag_configure(status,foreground=color)
        return tree

    def text(self,parent):
        return tk.Text(parent,wrap='word',font=('TkDefaultFont',11),padx=10,pady=10,state='disabled')

    def set_text(self,widget,value):
        if widget.get('1.0','end-1c') == value:return
        position=widget.yview();widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',value);widget.configure(state='disabled');widget.yview_moveto(position[0])

    def split_details(self,parent):
        panes=ttk.Panedwindow(parent,orient='horizontal');panes.pack(fill='both',expand=True,pady=8)
        left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=1);panes.add(right,weight=3)
        listing=tk.Listbox(left,exportselection=False,font=('TkDefaultFont',11),activestyle='dotbox');listing.pack(fill='both',expand=True)
        text=self.text(right);text.pack(fill='both',expand=True)
        return listing,text

    def scroll_frame(self,parent):
        outer=ttk.Frame(parent);outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,highlightthickness=0);scroll=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        frame=ttk.Frame(canvas);window=canvas.create_window((0,0),window=frame,anchor='nw')
        frame.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        return frame

    def _build_symptoms(self):
        frame=self.frames['symptoms']
        ttk.Label(frame,text='Search reported symptoms or context').pack(anchor='w')
        self.symptom_entry=ttk.Entry(frame,textvariable=self.search_var);self.symptom_entry.pack(fill='x',pady=5)
        self.symptom_count=ttk.Label(frame);self.symptom_count.pack(anchor='w')
        content=self.scroll_frame(frame)
        self.choice_widgets=[]
        for title,field,vocabulary in [('Symptoms','symptoms',self.meta['symptoms_en']),('Context','context',self.meta['context_en'])]:
            box=ttk.LabelFrame(content,text=title,padding=8);box.pack(fill='x',pady=5)
            store=self.symptom_vars if field=='symptoms' else self.context_vars
            for i,(key,label) in enumerate(vocabulary.items()):
                var=tk.BooleanVar();store[key]=var
                widget=ttk.Checkbutton(box,text=label,variable=var);widget.grid(row=i//2,column=i%2,sticky='w',padx=8,pady=3)
                self.choice_widgets.append((widget,label+' '+key))
            box.columnconfigure(0,weight=1);box.columnconfigure(1,weight=1)
        manual=ttk.LabelFrame(content,text='Manual measurements',padding=8);manual.pack(fill='x',pady=5)
        specs=dict(self.meta['derived'])
        specs.update({r['key']:r for r in self.meta['readings'] if r['category']=='symptom'})
        for i,(key,spec) in enumerate(specs.items()):
            ttk.Label(manual,text=(spec.get('label') or key.replace('_',' '))+' ('+spec.get('unit','')+')').grid(row=i,column=0,sticky='w',pady=4)
            var=tk.StringVar();self.manual_vars[key]=var
            ttk.Entry(manual,textvariable=var,width=16).grid(row=i,column=1,padx=12)
        exposure=ttk.LabelFrame(content,text='Actual recent exposures',padding=8);exposure.pack(fill='x',pady=5)
        ttk.Label(exposure,text='Medication / allergen names, comma-separated. Report only exposures that occurred.').pack(anchor='w')
        ttk.Entry(exposure,textvariable=self.exposures_var).pack(fill='x',pady=5)
        ttk.Button(frame,text='Save reports & assess',command=self.save_symptoms).pack(anchor='e',pady=8)

    def _build_medication(self):
        frame=self.frames['medication']
        ttk.Label(frame,text='Recorded allergies (comma-separated; use unknown if not established)').pack(anchor='w')
        ttk.Entry(frame,textvariable=self.allergies_var).pack(fill='x',pady=6)
        ttk.Button(frame,text='Save allergy history',command=self.save_allergies).pack(anchor='w')
        ttk.Separator(frame).pack(fill='x',pady=16)
        ttk.Label(frame,text='Medication: one active ingredient').pack(anchor='w')
        self.med_combo=ttk.Combobox(frame,textvariable=self.med_var,values=sorted(self.monitor.allergy_guard.known),width=50)
        self.med_combo.pack(anchor='w',pady=6)
        ttk.Button(frame,text='Check medication against this profile',command=self.check_medication).pack(anchor='w')
        self.med_status=ttk.Label(frame,text='Choose an ingredient and run the check.',wraplength=900);self.med_status.pack(anchor='w',pady=12)
        ttk.Label(frame,text='Manual record note (no dose is calculated by the app)').pack(anchor='w')
        ttk.Entry(frame,textvariable=self.med_note).pack(fill='x',pady=6)
        self.record_button=ttk.Button(frame,text='Record medication use',command=self.record_medication,state='disabled');self.record_button.pack(anchor='w')
        ttk.Label(frame,text='Known allergy matches are blocked. Unknown products and uncertain related-drug reactions require review. Other clinical contraindications still apply.',wraplength=900).pack(anchor='w',pady=18)

    def _build_forecasts(self):
        frame=self.frames['forecasts']
        bar=ttk.Frame(frame);bar.pack(fill='x')
        doses=[r['key'] for r in self.meta['readings'] if r['category']=='radiation']
        ttk.Combobox(bar,textvariable=self.forecast_key,values=doses,state='readonly',width=32).pack(side='left')
        ttk.Label(bar,text='Daily rate').pack(side='left',padx=8);ttk.Entry(bar,textvariable=self.forecast_rate,width=8).pack(side='left')
        ttk.Label(bar,text='Days ahead').pack(side='left',padx=8);ttk.Entry(bar,textvariable=self.forecast_days,width=6).pack(side='left')
        ttk.Button(bar,text='Calculate scenario',command=self.calculate_forecast).pack(side='left',padx=8)
        self.forecast_text=self.text(frame);self.forecast_text.pack(fill='both',expand=True,pady=10)
        self.forecast_text.configure(height=8)
        ttk.Label(frame,text='Measured-history projections').pack(anchor='w')
        self.measured_forecast_text=self.text(frame);self.measured_forecast_text.configure(height=8);self.measured_forecast_text.pack(fill='both',expand=True,pady=8)
        ttk.Label(frame,text='Conditional projection; no current alarm is generated by a future-rate scenario.').pack(anchor='w')

    def load_crew(self):
        crew=self.monitor.list_profiles();ids=[x['id'] for x in crew]
        self.crew_select.configure(values=ids)
        if ids and self.aid not in ids:self.select_crew(ids[0])

    def select_crew(self,aid):
        self.aid=aid;self.crew_var.set(aid);self.snapshot=self.monitor.snapshot(aid)
        state=self.snapshot.get('state',{})
        for key,var in self.symptom_vars.items():var.set(key in state.get('symptoms',[]))
        for key,var in self.context_vars.items():var.set(key in state.get('context',[]))
        for key,var in self.manual_vars.items():var.set(value_text(state.get('readings',{}).get(key)) if key in state.get('readings',{}) else '')
        self.exposures_var.set(', '.join(state.get('reported_exposures',[])))
        self.allergies_var.set(', '.join(self.snapshot['profile'].get('medical_history',{}).get('allergies',[])))
        self.last_findings=None;self.reset_medication();self.filter_library();self.refresh();self.refresh_history()
        self.set_text(self.forecast_text,'Manual scenario for '+aid+': enter a future rate and click Calculate scenario. A verified current exposure total is required.')
        self.set_text(self.profile_text,json.dumps(self.snapshot['profile'],indent=2))

    def row_values(self,row):
        baseline=row.get('baseline')
        baseline_text=(value_text(baseline['value'])+' '+baseline['unit']) if baseline else 'Not supplied'
        if baseline and baseline['unit'] != row['unit']:baseline_text+=' [different unit]'
        return [row['label'],value_text(row.get('value'))+' '+row['unit'],baseline_text,row['status'].replace('_',' '),
                str(row.get('source') or '—')+' / '+str(row.get('timestamp') or '—'),row.get('reason','')]

    def update_tree(self,tree,rows):
        wanted={r['key'] for r in rows}
        for key in tree.get_children():
            if key not in wanted:tree.delete(key)
        for row in rows:
            key=row['key'];values=self.row_values(row)
            if tree.exists(key):
                if tuple(tree.item(key,'values')) != tuple(map(str,values)):tree.item(key,values=values,tags=(row['status'],))
            else:tree.insert('', 'end', iid=key,values=values,tags=(row['status'],))

    def refresh(self):
        if not self.aid:return
        self.snapshot=self.monitor.snapshot(self.aid)
        snap=self.snapshot;allergies=self.monitor.allergy_guard.allergies(snap['profile'])[0]
        self.status.configure(text=f"{self.aid} · Mission day {snap['mission_day'] or 'not started'}/{snap['profile']['mission_details']['duration_days']} · {snap['assessment']['overall']} · {snap['active_source'].upper()} · Allergies: {', '.join(allergies) or 'none recorded'}")
        self.warning.configure(text=f"{len(snap['alerts'])} pending warnings" if snap['alerts'] else 'No pending warnings',
                               style='Warning.TLabel' if snap['alerts'] else 'TLabel')
        job=self.simulator.status()['active'].get(self.aid)
        self.sim_status.configure(text='Running: '+job['mode'] if job else 'Stopped')
        self.update_tree(self.live_tree,visible_live_rows(snap,self.meta['readings']))
        live_keys={r['key'] for r in visible_live_rows(snap,self.meta['readings'])}
        categories={r['key']:r['category'] for r in self.meta['readings']}
        self.update_tree(self.results_tree,[r for r in snap['readings'] if categories.get(r['key']) in {'blood_panel','radiation'}])
        findings=snap['assessment']['findings']
        signature=json.dumps(findings,sort_keys=True)
        if signature != self.last_findings:
            selected=self.finding_list.curselection();oldkey=self.finding_items[selected[0]]['rule_id'] if selected and selected[0]<len(self.finding_items) else None
            self.finding_items=findings;self.finding_list.delete(0,'end')
            for finding in findings:self.finding_list.insert('end',finding['level']+' · '+finding['name'])
            index=next((i for i,f in enumerate(findings) if f['rule_id']==oldkey),0)
            if findings:self.finding_list.selection_set(index)
            self.last_findings=signature;self.show_finding()
        if not self.forecast_text.get('1.0','end-1c'):
            self.set_text(self.forecast_text,'A scenario requires a known current dose total. Import an appropriate dose report first.')
        measured=[item for item in snap.get('forecasts',[]) if item.get('status')=='projected']
        if measured:self.set_text(self.measured_forecast_text,json.dumps(measured,indent=2))
        else:
            reasons=sorted({item.get('reason','Insufficient exposure data') for item in snap.get('forecasts',[])})
            self.set_text(self.measured_forecast_text,'No measured-history projection available.\n\n'+'\n'.join(reasons))

    def treatment_text(self,item):
        lines=[item.get('treatment_name','Treatment reference')]
        safety=item.get('allergy_safety',{})
        if safety:lines += ['ALLERGY CHECK: '+safety.get('status','').upper(),safety.get('reason','')]
        lines += [item.get('indication','')]
        lines += list(item.get('instructions',[]))
        lines += ['Dose in source: '+item.get('dosage','Not specified'), 'Warnings: '+item.get('warnings_and_interactions','Not specified')]
        lines += list(item.get('sources',[]))
        return '\n'.join(x for x in lines if x)

    def show_finding(self):
        selected=self.finding_list.curselection()
        if not selected or not self.finding_items:
            self.set_text(self.finding_text,'No active findings. Missing data is not evidence that a condition is absent.');return
        finding=self.finding_items[selected[0]]
        lines=[finding['name'], 'Level: '+finding['level'],finding.get('logic','')]
        if finding.get('allergy_evidence'):lines+=['Matched reported allergy exposure:',json.dumps(finding['allergy_evidence'],indent=2)]
        lines+=['Evidence:',json.dumps(finding.get('evidence',[]),indent=2),'Confirmation:',*finding.get('confirmation',[])]
        if finding.get('hide_therapy'):lines+=['Routine treatment withheld because red flags require evaluation.']
        else:lines += [self.treatment_text(t) for t in finding.get('treatments',[])]
        self.set_text(self.finding_text,'\n\n'.join(str(x) for x in lines if x))

    def filter_library(self):
        if not self.aid:return
        old=self.library_list.curselection();oldid=self.library_items[old[0]]['condition_id'] if old and old[0]<len(self.library_items) else None
        query=self.library_search.get()
        self.library_items=[entry for entry in self.meta['treatment_library'] if matches(json.dumps(entry,ensure_ascii=False),query)]
        self.library_list.delete(0,'end')
        for entry in self.library_items:self.library_list.insert('end',entry['condition_name'])
        self.library_count.configure(text=f'{len(self.library_items)} matching topics' if self.library_items else 'No matching treatments')
        if self.library_items:self.library_list.selection_set(next((i for i,e in enumerate(self.library_items) if e['condition_id']==oldid),0))
        self.show_library()

    def show_library(self):
        selected=self.library_list.curselection()
        if not selected or not self.library_items:self.set_text(self.library_text,'No matching treatments.');return
        entry=self.library_items[selected[0]]
        profile=self.monitor.snapshot(self.aid)['profile']
        text=entry['condition_name']+'\n\n'+'\n\n'.join(self.treatment_text(self.monitor.allergy_guard.treatment(profile,t)) for t in entry['treatments'])
        self.set_text(self.library_text,text)

    def filter_symptoms(self):
        count=0
        for widget,text in self.choice_widgets:
            if matches(text,self.search_var.get()):widget.grid();count+=1
            else:widget.grid_remove()
        self.symptom_count.configure(text=f'{count} matching symptoms/context items' if count else 'No matching symptoms or context')

    def save_symptoms(self):
        def save():
            values={key:float(var.get()) if var.get().strip() else None for key,var in self.manual_vars.items()}
            self.monitor.update_symptoms(self.aid,{'symptoms':[k for k,v in self.symptom_vars.items() if v.get()],
                'context':[k for k,v in self.context_vars.items() if v.get()], 'readings':values,
                'reported_exposures':[x.strip() for x in self.exposures_var.get().split(',') if x.strip()]})
            self.refresh()
        self.call(save)

    def save_allergies(self):
        def save():
            values=[x.strip() for x in self.allergies_var.get().split(',') if x.strip()]
            self.monitor.update_allergies(self.aid,{'allergies':values})
            self.reset_medication();self.last_findings=None;self.refresh();self.show_library()
            self.set_text(self.profile_text,json.dumps(self.snapshot['profile'],indent=2))
        self.call(save)

    def reset_medication(self):
        self.med_check=None
        if hasattr(self,'record_button'):
            self.record_button.configure(state='disabled');self.med_status.configure(text='Run an allergy check before recording this medication.')

    def check_medication(self):
        result=self.call(self.monitor.check_medication,self.aid,{'medication':self.med_var.get()})
        if result:
            self.med_check=result;self.med_status.configure(text=result['status'].upper()+': '+result['reason'])
            self.record_button.configure(state='normal' if result['recording_allowed'] else 'disabled')

    def record_medication(self):
        result=self.call(self.monitor.record_medication,self.aid,{'medication':self.med_var.get(),'note':self.med_note.get()})
        if result:self.med_status.configure(text='Recorded in session history.');self.refresh_history()

    def simulate(self,action):
        result=self.call(self.simulator.control,self.aid,{'action':action,'mode':MODES[self.mode_var.get()],'interval_seconds':2})
        if result:self.refresh()

    def import_json(self,kind):
        name=filedialog.askopenfilename(parent=self.root,title='Import '+kind+' JSON',filetypes=[('JSON files','*.json'),('All files','*')])
        if not name:return
        def perform():
            document=strict_json(Path(name).read_text(encoding='utf-8'))
            if kind=='profile':
                result=self.monitor.add_profile(document);self.load_crew();self.select_crew(result['id'])
            elif kind=='lab':self.monitor.import_lab(self.aid,document)
            else:self.monitor.ingest(self.aid,normalize_packet(document,self.monitor.kb))
            self.refresh();self.refresh_history()
        self.call(perform)

    def refresh_history(self):
        if self.aid:self.set_text(self.history_text,json.dumps(self.monitor.history(self.aid),indent=2))

    def export_history(self):
        self.export_json(self.monitor.history(self.aid),self.aid+'_history.json')

    def export_profile(self):
        self.export_json(self.snapshot['profile'],self.aid+'_profile.json')

    def export_json(self,document,default):
        filename=filedialog.asksaveasfilename(parent=self.root,initialfile=default,defaultextension='.json',filetypes=[('JSON files','*.json')])
        if filename:self.call(Path(filename).write_text,json.dumps(document,indent=2),encoding='utf-8')

    def calculate_forecast(self):
        def calculate():
            key=self.forecast_key.get();unit=self.monitor.kb.signals[key]['unit']
            result=self.monitor.forecast(self.aid,{'key':key,'unit':unit,'daily_rate':float(self.forecast_rate.get()),'horizon_days':float(self.forecast_days.get())})
            self.set_text(self.forecast_text,json.dumps(result,indent=2))
        self.call(calculate)

    def show_alerts(self):
        if not self.aid:return
        window=tk.Toplevel(self.root);window.title('Pending warnings — '+self.aid);window.geometry('880x500')
        listing,text=self.split_details(window)
        events=self.monitor.snapshot(self.aid)['alerts']
        for event in events:listing.insert('end',event.get('severity','WARNING')+' · '+event.get('message','Warning'))
        def details(_=None):
            selected=listing.curselection()
            if selected:self.set_text(text,json.dumps(events[selected[0]],indent=2))
        def acknowledge():
            selected=listing.curselection()
            if selected:
                event=events.pop(selected[0]);self.monitor.acknowledge(self.aid,event['id']);listing.delete(selected[0]);self.set_text(text,'Acknowledged. The measurement is unchanged.');self.refresh()
        def acknowledge_all():
            for event in list(events):self.monitor.acknowledge(self.aid,event['id'])
            events.clear();listing.delete(0,'end');self.set_text(text,'All listed warnings acknowledged. Their history and measurements remain stored.');self.refresh()
        listing.bind('<<ListboxSelect>>',details)
        ttk.Button(window,text='Acknowledge selected warning',command=acknowledge).pack(pady=8)
        ttk.Button(window,text='Acknowledge all listed warnings',command=acknowledge_all).pack(pady=(0,8))
        if events:listing.selection_set(0);details()

    def tab_changed(self,_=None):
        key=next((key for key,frame in self.frames.items() if str(frame)==self.tabs.select()),None)
        if key=='history':self.refresh_history()
        elif key=='profile' and self.snapshot:self.set_text(self.profile_text,json.dumps(self.snapshot['profile'],indent=2))

    def show(self):
        self.root.deiconify();self.root.lift()

    def hide(self):
        self.root.withdraw()

    def quit(self):
        self.stop.set()
        if getattr(self,'after_id',None):self.root.after_cancel(self.after_id)
        self.root.destroy()

    def poll(self):
        if getattr(self,'after_id',None):
            self.root.after_cancel(self.after_id)
            self.after_id=None
        if self.stop.is_set():
            self.root.destroy();return
        if self.window_signals.is_set():self.window_signals.clear();self.show()
        new=[]
        while True:
            try:new.append(self.notifications.get_nowait())
            except queue.Empty:break
        if new:
            if self.root.state() in {'withdrawn','iconic'}:
                aid=new[0].get('aid') if isinstance(new[0],dict) else None
                if aid and aid != self.aid:self.select_crew(aid)
                self.show()
            elif not self.root.tk.call('focus','-displayof',str(self.root)):
                self.root.lift()
            self.root.bell()
        try:self.refresh()
        except Exception as exc:self.status.configure(text='Monitor error: '+str(exc))
        self.after_id=self.root.after(500,self.poll)


def desktop_loop(monitor,simulator,notifications,stop,window_signals,hidden=False,root=None):
    root=root or tk.Tk()
    app=NativeApp(root,monitor,simulator,notifications,stop,window_signals,hidden=hidden)
    try:root.mainloop()
    except KeyboardInterrupt:app.quit()
    return app
